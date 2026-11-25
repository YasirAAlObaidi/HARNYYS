"""The whole path in one process: signed WhatsApp webhook -> database -> agent turn -> tools -> outbox -> Graph API.

Real pieces: the FastAPI app, Postgres, the catalogue copy, the tool registry and every workflow, wired by
yyai.bootstrap from a config file loaded with load_config. Mocked pieces: the model server and Meta's Graph API
(respx). The model's replies are scripted, so what is under test is everything around the model.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
import respx
import yaml

from yyai.bootstrap import build
from yyai.core.config import Config, load_config
from yyai.entry.api.app import create_app
from yyai.workflows.container import Workflows

pytestmark = pytest.mark.db

APP_SECRET = "e2e-app-secret"
VERIFY_TOKEN = "e2e-verify-token"
ACCESS_TOKEN = "e2e-access-token"
PHONE_NUMBER_ID = "109876543210"
MODEL_KEY = "e2e-model-key"
MODEL_URL = "https://model.test/v1/chat/completions"
CUSTOMER = "971501234567"
CUSTOMER_NAME = "أحمد المنصوري"
QUESTION = "كم سعر قهوة كولومبية سوبريمو ١ كجم؟"
LIVE_PRICE = 139.5  # the demo file says 135: the difference proves the price was read live, not from the copy
MISSING = object()


# --- setup -----------------------------------------------------------------------------------------------------


def write_config(
    tmp_path: Path,
    kahraman_dir: Path,
    database_url: str,
    catalogue_path: Path,
    *,
    fallback_reply: Any = MISSING,
    auto_send: bool | None = None,
) -> Path:
    """The Kahraman demo config, pointed at the test database, a fake model URL and dummy secrets."""
    raw = yaml.safe_load((kahraman_dir / "config.yaml").read_text(encoding="utf-8"))
    raw["database_url"] = database_url
    model = raw["models"]["chat.default"]
    model.update(base_url="https://model.test/v1", api_key=MODEL_KEY, external=False, allow_external=False)
    model["params"] = {"temperature": 0.3, "max_tokens": 800}  # drops the OpenRouter-only routing block
    raw["inventory"]["settings"]["path"] = str(catalogue_path)
    raw["channels"]["whatsapp"]["settings"] = {
        "phone_number_id": PHONE_NUMBER_ID,
        "access_token": ACCESS_TOKEN,
        "app_secret": APP_SECRET,
        "verify_token": VERIFY_TOKEN,
        "graph_version": "v23.0",
    }
    if fallback_reply is not MISSING:
        raw["agent"]["fallback_reply"] = fallback_reply
    if auto_send is not None:
        raw["agent"]["auto_send"] = auto_send
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


@dataclass
class Env:
    config: Config
    workflows: Workflows
    http: httpx.AsyncClient
    sql: psycopg.Connection
    catalogue_path: Path

    @property
    def graph_url(self) -> str:
        return f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"

    async def post_whatsapp(
        self, body: bytes, headers: dict[str, str] | None = None, *, signed: bool = True
    ) -> httpx.Response:
        sent = {"Content-Type": "application/json", **(sign(body) if signed else {}), **(headers or {})}
        return await self.http.post("/api/webhooks/whatsapp", content=body, headers=sent)

    def one(self, query: str, *params: Any) -> dict[str, Any]:
        rows = self.sql.execute(query, params).fetchall()
        assert len(rows) == 1, f"expected one row, got {rows}"
        return rows[0]

    def count(self, table: str, where: str = "true") -> int:
        return self.one(f"SELECT count(*) AS n FROM {table} WHERE {where}")["n"]


@pytest.fixture
async def make_env(
    clean_database: str, tmp_path: Path, kahraman_dir: Path, sample_catalogue: Path, sql: psycopg.Connection
) -> AsyncIterator[Callable[..., Awaitable[Env]]]:
    """A factory, so a test can ask for a variant of the config. Everything it builds is closed afterwards."""
    opened: list[tuple[httpx.AsyncClient, Workflows]] = []

    async def factory(**config_overrides: Any) -> Env:
        catalogue_path = tmp_path / "catalogue.json"
        catalogue_path.write_text(sample_catalogue.read_text(encoding="utf-8"), encoding="utf-8")
        config = load_config(
            write_config(tmp_path, kahraman_dir, clean_database, catalogue_path, **config_overrides)
        )
        workflows = build(config)
        http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(workflows)), base_url="http://test"
        )
        opened.append((http, workflows))
        await workflows.catalogue_sync.run()
        return Env(config=config, workflows=workflows, http=http, sql=sql, catalogue_path=catalogue_path)

    yield factory

    for http, workflows in opened:
        await http.aclose()
        await workflows.aclose()


def sign(body: bytes, secret: str = APP_SECRET) -> dict[str, str]:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}


def whatsapp_body(
    text: str = QUESTION,
    message_id: str = "wamid.E2E1",
    *,
    timestamp: int | None = None,
    sender: str = CUSTOMER,
) -> bytes:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "102290129340398",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550001111",
                                "phone_number_id": PHONE_NUMBER_ID,
                            },
                            "contacts": [{"profile": {"name": CUSTOMER_NAME}, "wa_id": sender}],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": message_id,
                                    "timestamp": str(
                                        timestamp if timestamp is not None else int(time.time())
                                    ),
                                    "text": {"body": text},
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    return json.dumps(payload, ensure_ascii=False).encode()


def completion(content: str | None = None, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-e2e",
        "choices": [
            {"index": 0, "message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


def quote_price_call(query: str = "قهوة كولومبية سوبريمو ١ كجم") -> dict[str, Any]:
    return {
        "id": "call_quote_1",
        "type": "function",
        "function": {"name": "quote_price", "arguments": json.dumps({"query": query}, ensure_ascii=False)},
    }


FINAL_ANSWER = f"سعر قهوة كولومبية سوبريمو 1 كجم هو {LIVE_PRICE} درهم شامل ضريبة القيمة المضافة."
GRAPH_OK = {"messages": [{"id": "wamid.TEST"}]}


def raise_price_in_the_file(env: Env) -> None:
    """Change the price in the inventory file after the catalogue copy was made, as the ERP would."""
    data = json.loads(env.catalogue_path.read_text(encoding="utf-8"))
    next(item for item in data["items"] if item["code"] == "SAMPLE-002")["price"] = LIVE_PRICE
    env.catalogue_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# --- the full path ---------------------------------------------------------------------------------------------------


async def test_whatsapp_question_to_priced_answer(make_env, mock_http: respx.MockRouter) -> None:
    env: Env = await make_env()
    assert env.count("catalogue_items") == 12
    raise_price_in_the_file(env)

    # 1. Meta delivers the customer's message. Twice, as Meta does when it has not heard back in time.
    body = whatsapp_body()
    first = await env.post_whatsapp(body)
    assert first.status_code == 200
    assert first.json() == {"received": 1, "new": 1}
    second = await env.post_whatsapp(body)
    assert second.status_code == 200
    assert second.json() == {"received": 1, "new": 0}
    assert env.count("messages", "direction = 'in'") == 1
    assert env.count("turns") == 1
    conversation = env.one("SELECT * FROM conversations")
    assert (conversation["external_user_id"], conversation["customer_name"]) == (CUSTOMER, CUSTOMER_NAME)

    # 2. The worker runs the turn: the model asks for a price, the tool answers, the model replies.
    model = mock_http.post(MODEL_URL).mock(
        side_effect=[
            httpx.Response(200, json=completion(tool_calls=[quote_price_call()])),
            httpx.Response(200, json=completion(FINAL_ANSWER)),
        ]
    )
    assert await env.workflows.turns.run_once() is True
    assert await env.workflows.turns.run_once() is False  # the duplicate queued nothing
    assert model.call_count == 2

    first_request = json.loads(model.calls[0].request.content)
    assert model.calls[0].request.headers["Authorization"] == f"Bearer {MODEL_KEY}"
    assert first_request["model"] == "qwen/qwen3.8-27b"
    assert {tool["function"]["name"] for tool in first_request["tools"]} == {
        "search_products", "quote_price", "product_details", "list_categories",
    }  # fmt: skip
    system, *rest = first_request["messages"]
    assert system["role"] == "system"
    assert "Kahraman" in system["content"]
    assert "{client_name}" not in system["content"]  # the prompt placeholders were filled in
    assert [(m["role"], m["content"]) for m in rest] == [("user", QUESTION)]

    second_request = json.loads(model.calls[1].request.content)
    roles = [m["role"] for m in second_request["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assistant, tool_message = second_request["messages"][2:]
    assert assistant["tool_calls"][0]["id"] == "call_quote_1"
    assert tool_message["tool_call_id"] == "call_quote_1"
    quote = json.loads(tool_message["content"])
    assert quote["found"] is True
    assert quote["code"] == "SAMPLE-002"
    assert quote["price"] == LIVE_PRICE  # from the inventory file, not the 135 in our copy
    assert quote["price_source"] == "live"
    assert (quote["currency"], quote["vat_included"], quote["in_stock"]) == ("AED", True, True)
    assert "note" not in quote  # no "live price not available" warning

    # 3. The reply is queued, then the outbox sends it through the Graph API.
    queued = env.one("SELECT status, text FROM outbox")
    assert (queued["status"], queued["text"]) == ("pending", FINAL_ANSWER)
    assert env.one("SELECT state FROM turns")["state"] == "sending"

    graph = mock_http.post(env.graph_url).mock(return_value=httpx.Response(200, json=GRAPH_OK))
    assert await env.workflows.outbox.deliver_once() is True
    assert await env.workflows.outbox.deliver_once() is False

    assert graph.call_count == 1
    sent = graph.calls[0].request
    assert sent.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert json.loads(sent.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": CUSTOMER,
        "type": "text",
        "text": {"preview_url": False, "body": FINAL_ANSWER},
    }
    outbox = env.one("SELECT status, provider_message_id, attempts FROM outbox")
    assert (outbox["status"], outbox["provider_message_id"], outbox["attempts"]) == ("sent", "wamid.TEST", 1)
    turn = env.one("SELECT state, steps, error FROM turns")
    assert (turn["state"], turn["steps"], turn["error"]) == ("sent", 2, None)

    # 4. Everything the agent did is in the audit log.
    audit = env.sql.execute("SELECT kind, name, data FROM audit_log ORDER BY id").fetchall()
    assert [(row["kind"], row["name"]) for row in audit] == [
        ("model_reply", "chat.default"),
        ("tool_call", "quote_price"),
        ("model_reply", "chat.default"),
    ]
    assert audit[0]["data"]["tool_calls"] == ["quote_price"]
    assert audit[1]["data"]["args"] == {"query": "قهوة كولومبية سوبريمو ١ كجم"}
    assert json.loads(audit[1]["data"]["result"])["price"] == LIVE_PRICE
    assert audit[2]["data"]["text"] == FINAL_ANSWER
    assert audit[2]["data"]["usage"]["total_tokens"] == 120

    # 5. Staff can read the conversation through the API.
    conversations = (await env.http.get("/api/conversations")).json()
    assert [(c["external_user_id"], c["customer_name"]) for c in conversations] == [(CUSTOMER, CUSTOMER_NAME)]
    messages = (await env.http.get(f"/api/conversations/{conversations[0]['id']}/messages")).json()
    assert [(m["direction"], m["text"]) for m in messages] == [("in", QUESTION), ("out", FINAL_ANSWER)]


async def test_a_second_message_after_the_reply_sees_the_whole_conversation(
    make_env, mock_http: respx.MockRouter
) -> None:
    env: Env = await make_env()
    model = mock_http.post(MODEL_URL).mock(
        side_effect=[
            httpx.Response(200, json=completion("أهلاً بك")),
            httpx.Response(200, json=completion("تفضل")),
        ]
    )
    mock_http.post(env.graph_url).mock(return_value=httpx.Response(200, json=GRAPH_OK))

    await env.post_whatsapp(whatsapp_body("سلام", "wamid.A"))
    await env.workflows.turns.run_once()
    await env.workflows.outbox.deliver_once()
    await env.post_whatsapp(whatsapp_body("عندكم مطحنة؟", "wamid.B"))
    await env.workflows.turns.run_once()

    history = [(m["role"], m["content"]) for m in json.loads(model.calls[1].request.content)["messages"][1:]]
    assert history == [("user", "سلام"), ("assistant", "أهلاً بك"), ("user", "عندكم مطحنة؟")]


# --- webhook edge cases ---------------------------------------------------------------------------------------------------


async def test_verification_handshake(make_env) -> None:
    env: Env = await make_env()
    good = {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1158201444"}

    response = await env.http.get("/api/webhooks/whatsapp", params=good)
    assert response.status_code == 200
    assert response.text == "1158201444"

    wrong = await env.http.get("/api/webhooks/whatsapp", params={**good, "hub.verify_token": "wrong"})
    assert wrong.status_code == 403
    missing = await env.http.get(
        "/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.challenge": "1"}
    )
    assert missing.status_code == 403
    non_ascii = await env.http.get("/api/webhooks/whatsapp", params={**good, "hub.verify_token": "töken"})
    assert non_ascii.status_code == 403  # refused, not a server error
    unknown = await env.http.get("/api/webhooks/telegram", params=good)
    assert unknown.status_code == 404
    webchat = await env.http.get("/api/webhooks/webchat", params=good)
    assert webchat.status_code == 403  # web chat has no handshake


async def test_bad_signature_is_rejected_and_nothing_is_stored(make_env) -> None:
    env: Env = await make_env()
    body = whatsapp_body()

    forged = await env.post_whatsapp(body, sign(body, secret="not-the-app-secret"))
    assert forged.status_code == 401
    unsigned = await env.post_whatsapp(body, signed=False)
    assert unsigned.status_code == 401
    # Header bytes outside ASCII (servers decode them as latin-1) must be refused, not crash the check.
    garbage = await env.post_whatsapp(body, {"X-Hub-Signature-256": "sha256=éé".encode("latin-1")})  # type: ignore[dict-item]
    assert garbage.status_code == 401

    assert env.count("conversations") == 0
    assert env.count("messages") == 0
    assert env.count("turns") == 0


async def test_signed_but_unreadable_body_is_a_400(make_env) -> None:
    env: Env = await make_env()
    response = await env.post_whatsapp(b"{this is not json")
    assert response.status_code == 400
    assert env.count("messages") == 0


async def test_status_only_webhook_is_acknowledged_without_queueing_anything(make_env) -> None:
    env: Env = await make_env()
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1",
                "changes": [
                    {"field": "messages", "value": {"statuses": [{"id": "wamid.X", "status": "read"}]}}
                ],
            }
        ],
    }
    response = await env.post_whatsapp(json.dumps(payload).encode())
    assert response.status_code == 200
    assert response.json() == {"received": 0, "new": 0}
    assert env.count("turns") == 0


async def test_unknown_channel_is_a_404(make_env) -> None:
    env: Env = await make_env()
    response = await env.http.post("/api/webhooks/telegram", content=b"{}")
    assert response.status_code == 404


# --- failures -----------------------------------------------------------------------------------------------------------------


async def test_model_http_500_still_sends_the_configured_fallback_reply(
    make_env, mock_http: respx.MockRouter
) -> None:
    env: Env = await make_env()
    fallback = env.config.agent.fallback_reply
    assert fallback and "عذرًا" in fallback  # the demo config has a bilingual fallback
    model = mock_http.post(MODEL_URL).mock(return_value=httpx.Response(500, text="model server on fire"))
    await env.post_whatsapp(whatsapp_body())

    assert await env.workflows.turns.run_once() is True

    assert model.call_count == 1
    outbox = env.one("SELECT status, text FROM outbox")
    assert (outbox["status"], outbox["text"]) == ("pending", fallback)
    assert env.one("SELECT state FROM turns")["state"] == "sending"
    error = env.one("SELECT name, data FROM audit_log WHERE kind = 'error'")
    assert error["name"] == "IntegrationError"
    assert "500" in error["data"]["error"]

    graph = mock_http.post(env.graph_url).mock(return_value=httpx.Response(200, json=GRAPH_OK))
    assert await env.workflows.outbox.deliver_once() is True
    assert json.loads(graph.calls[0].request.content)["text"]["body"] == fallback
    assert env.one("SELECT state FROM turns")["state"] == "sent"


async def test_model_failure_without_a_fallback_fails_the_turn_and_sends_nothing(
    make_env, mock_http: respx.MockRouter
) -> None:
    env: Env = await make_env(fallback_reply=None)
    mock_http.post(MODEL_URL).mock(return_value=httpx.Response(500, text="down"))
    await env.post_whatsapp(whatsapp_body())

    assert await env.workflows.turns.run_once() is True

    turn = env.one("SELECT state, error FROM turns")
    assert turn["state"] == "failed"
    assert "IntegrationError" in turn["error"]
    assert env.count("outbox") == 0
    assert await env.workflows.outbox.deliver_once() is False


async def test_a_tool_the_model_invents_gets_one_correction_and_the_customer_still_gets_an_answer(
    make_env, mock_http: respx.MockRouter
) -> None:
    env: Env = await make_env()
    invented = {
        "id": "call_x",
        "type": "function",
        "function": {"name": "send_discount_code", "arguments": "{}"},
    }
    model = mock_http.post(MODEL_URL).mock(
        side_effect=[
            httpx.Response(200, json=completion(tool_calls=[invented])),
            httpx.Response(200, json=completion("سأطلب من أحد الموظفين التواصل معك.")),
        ]
    )
    await env.post_whatsapp(whatsapp_body("أبغى خصم"))

    await env.workflows.turns.run_once()

    assert model.call_count == 2
    correction = [m for m in json.loads(model.calls[1].request.content)["messages"] if m["role"] == "tool"]
    assert "unknown tool 'send_discount_code'" in correction[0]["content"]
    assert env.one("SELECT text FROM outbox")["text"] == "سأطلب من أحد الموظفين التواصل معك."
    assert env.count("audit_log", "kind = 'tool_call'") == 0  # the invented tool never ran


async def test_a_model_that_never_stops_calling_tools_is_cut_off_and_asked_for_an_answer(
    make_env, mock_http: respx.MockRouter
) -> None:
    env: Env = await make_env()
    max_steps = env.config.agent.max_steps
    replies = [
        httpx.Response(200, json=completion(tool_calls=[quote_price_call()])) for _ in range(max_steps)
    ]
    replies.append(httpx.Response(200, json=completion("سيتواصل معك أحد موظفينا لتأكيد السعر.")))
    model = mock_http.post(MODEL_URL).mock(side_effect=replies)
    await env.post_whatsapp(whatsapp_body())

    await env.workflows.turns.run_once()

    assert model.call_count == max_steps + 1
    last = json.loads(model.calls[-1].request.content)
    assert "tools" not in last  # the final request offers no tools
    assert last["messages"][-1]["role"] == "system"
    assert env.one("SELECT text FROM outbox")["text"] == "سيتواصل معك أحد موظفينا لتأكيد السعر."
    assert env.one("SELECT steps FROM turns")["steps"] == max_steps + 1


async def test_graph_api_outage_retries_later_and_a_rejection_fails_the_turn(
    make_env, mock_http: respx.MockRouter
) -> None:
    env: Env = await make_env()
    mock_http.post(MODEL_URL).mock(return_value=httpx.Response(200, json=completion("مرحبا")))
    await env.post_whatsapp(whatsapp_body())
    await env.workflows.turns.run_once()

    graph = mock_http.post(env.graph_url).mock(return_value=httpx.Response(503, text="try later"))
    assert await env.workflows.outbox.deliver_once() is True
    outbox = env.one("SELECT status, attempts, last_error, next_attempt_at > now() AS later FROM outbox")
    assert (outbox["status"], outbox["attempts"], outbox["later"]) == ("pending", 1, True)
    assert "503" in outbox["last_error"]
    assert env.one("SELECT state FROM turns")["state"] == "sending"
    assert await env.workflows.outbox.deliver_once() is False  # not due yet

    env.sql.execute("UPDATE outbox SET next_attempt_at = now()")
    graph.mock(return_value=httpx.Response(400, json={"error": {"message": "(#131030) not in allowed list"}}))
    assert await env.workflows.outbox.deliver_once() is True
    assert env.one("SELECT status FROM outbox")["status"] == "failed"
    turn = env.one("SELECT state, error FROM turns")
    assert turn["state"] == "failed"
    assert "send failed" in turn["error"]


async def test_reply_after_the_24_hour_window_is_not_sent(make_env, mock_http: respx.MockRouter) -> None:
    env: Env = await make_env()
    mock_http.post(MODEL_URL).mock(return_value=httpx.Response(200, json=completion("مرحبا")))
    graph = mock_http.post(env.graph_url).mock(return_value=httpx.Response(200, json=GRAPH_OK))
    await env.post_whatsapp(whatsapp_body(timestamp=int(time.time()) - 25 * 3600))
    await env.workflows.turns.run_once()

    assert await env.workflows.outbox.deliver_once() is True

    assert graph.call_count == 0  # WhatsApp only allows template messages now
    assert env.one("SELECT status FROM outbox")["status"] == "failed"
    assert env.one("SELECT state FROM turns")["state"] == "failed"


# --- other channels and staff actions ---------------------------------------------------------------------------------------------


async def test_webchat_round_trip_needs_no_outside_service(make_env, mock_http: respx.MockRouter) -> None:
    env: Env = await make_env()
    mock_http.post(MODEL_URL).mock(return_value=httpx.Response(200, json=completion("أهلاً!")))
    body = json.dumps({"user_id": "web-42", "name": "Demo", "text": "مرحبا", "message_id": "web-1"}).encode()

    response = await env.http.post("/api/webhooks/webchat", content=body)
    assert response.status_code == 200
    assert response.json() == {"received": 1, "new": 1}
    await env.workflows.turns.run_once()
    assert await env.workflows.outbox.deliver_once() is True

    assert env.one("SELECT channel, external_user_id FROM conversations")["channel"] == "webchat"
    assert env.one("SELECT state FROM turns")["state"] == "sent"
    assert env.one("SELECT provider_message_id FROM outbox")["provider_message_id"].startswith("webchat-")


async def test_replies_wait_for_staff_approval_when_auto_send_is_off(
    make_env, mock_http: respx.MockRouter
) -> None:
    env: Env = await make_env(auto_send=False)
    mock_http.post(MODEL_URL).mock(return_value=httpx.Response(200, json=completion("مرحبا")))
    graph = mock_http.post(env.graph_url).mock(return_value=httpx.Response(200, json=GRAPH_OK))
    await env.post_whatsapp(whatsapp_body())
    await env.workflows.turns.run_once()

    outbox_id = env.one("SELECT id, status FROM outbox")
    assert outbox_id["status"] == "awaiting_approval"
    assert await env.workflows.outbox.deliver_once() is False
    assert graph.call_count == 0

    assert (await env.http.post("/api/outbox/999/approve")).status_code == 404
    approved = await env.http.post(f"/api/outbox/{outbox_id['id']}/approve")
    assert approved.status_code == 200
    assert approved.json() == {"approved": True, "id": outbox_id["id"]}
    assert (await env.http.post(f"/api/outbox/{outbox_id['id']}/approve")).status_code == 404  # only once

    assert await env.workflows.outbox.deliver_once() is True
    assert graph.call_count == 1


async def test_health_and_admin_catalogue_sync(make_env) -> None:
    env: Env = await make_env()

    health = await env.http.get("/api/health")
    assert (health.status_code, health.json()) == (200, {"status": "ok", "database": "ok"})

    env.sql.execute("DELETE FROM catalogue_items")
    synced = await env.http.post("/api/admin/catalogue/sync")
    assert (synced.status_code, synced.json()) == (200, {"synced": 12})
    assert env.count("catalogue_items") == 12


async def test_admin_sync_reports_an_unreadable_catalogue_as_a_502(make_env) -> None:
    env: Env = await make_env()
    env.catalogue_path.unlink()
    response = await env.http.post("/api/admin/catalogue/sync")
    assert response.status_code == 502
    assert env.count("catalogue_items") == 12  # the old copy is untouched
