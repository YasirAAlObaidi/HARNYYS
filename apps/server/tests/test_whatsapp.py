"""WhatsApp Cloud API handler: webhook signature, payload parsing, the 24-hour window and sending."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from yyai.core.errors import IntegrationError, SignatureError
from yyai.handlers.integrations.whatsapp_cloud.handler import MAX_TEXT, WhatsAppCloud

APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"
PHONE_NUMBER_ID = "109876543210"
ACCESS_TOKEN = "test-access-token"
GRAPH_VERSION = "v23.0"
MESSAGES_URL = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"

CUSTOMER = "971501234567"
TIMESTAMP = 1732550000


@pytest.fixture
def wa() -> WhatsAppCloud:
    return WhatsAppCloud(
        channel="whatsapp",
        phone_number_id=PHONE_NUMBER_ID,
        access_token=ACCESS_TOKEN,
        app_secret=APP_SECRET,
        verify_token=VERIFY_TOKEN,
        graph_version=GRAPH_VERSION,
    )


def sign(body: bytes, secret: str = APP_SECRET) -> dict[str, str]:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={digest}"}


def webhook(value_extra: dict[str, Any]) -> bytes:
    """A Cloud API webhook body in Meta's real envelope, with `value_extra` merged into `value`."""
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15550001111", "phone_number_id": PHONE_NUMBER_ID},
        **value_extra,
    }
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "102290129340398", "changes": [{"field": "messages", "value": value}]}],
    }
    return json.dumps(payload, ensure_ascii=False).encode()


def text_webhook(body: str = "كم سعر قهوة كولومبية؟", message_id: str = "wamid.TEXT1") -> bytes:
    return webhook(
        {
            "contacts": [{"profile": {"name": "Ahmed Al Mansoori"}, "wa_id": CUSTOMER}],
            "messages": [
                {
                    "from": CUSTOMER,
                    "id": message_id,
                    "timestamp": str(TIMESTAMP),
                    "text": {"body": body},
                    "type": "text",
                }
            ],
        }
    )


# --- signature ---------------------------------------------------------------


def test_valid_signature_passes(wa: WhatsAppCloud) -> None:
    body = text_webhook()
    messages = wa.parse_webhook(sign(body), body)
    assert len(messages) == 1


def test_signature_header_name_is_case_insensitive(wa: WhatsAppCloud) -> None:
    body = text_webhook()
    headers = {"x-hub-signature-256": sign(body)["X-Hub-Signature-256"]}
    assert len(wa.parse_webhook(headers, body)) == 1


def test_wrong_signature_raises(wa: WhatsAppCloud) -> None:
    body = text_webhook()
    with pytest.raises(SignatureError):
        wa.parse_webhook(sign(body, secret="some-other-secret"), body)


def test_missing_signature_raises(wa: WhatsAppCloud) -> None:
    with pytest.raises(SignatureError):
        wa.parse_webhook({}, text_webhook())


def test_empty_signature_raises(wa: WhatsAppCloud) -> None:
    with pytest.raises(SignatureError):
        wa.parse_webhook({"X-Hub-Signature-256": ""}, text_webhook())


def test_signature_without_sha256_prefix_raises(wa: WhatsAppCloud) -> None:
    body = text_webhook()
    bare = sign(body)["X-Hub-Signature-256"].removeprefix("sha256=")
    with pytest.raises(SignatureError):
        wa.parse_webhook({"X-Hub-Signature-256": bare}, body)


def test_body_changed_after_signing_raises(wa: WhatsAppCloud) -> None:
    body = text_webhook()
    headers = sign(body)
    with pytest.raises(SignatureError):
        wa.parse_webhook(headers, body.replace(b"971501234567", b"971509999999"))


def test_non_ascii_signature_header_is_a_signature_error_not_a_crash(wa: WhatsAppCloud) -> None:
    # hmac.compare_digest raises TypeError for non-ASCII str, which would turn a forged request into a 400/500.
    with pytest.raises(SignatureError):
        wa.parse_webhook({"X-Hub-Signature-256": "sha256=éé"}, text_webhook())


# --- parsing -----------------------------------------------------------------


def test_text_message_with_contact_name(wa: WhatsAppCloud) -> None:
    body = text_webhook("كم سعر قهوة كولومبية؟", message_id="wamid.TEXT1")
    (message,) = wa.parse_webhook(sign(body), body)
    assert message.channel == "whatsapp"
    assert message.source_id == "wamid.TEXT1"
    assert message.sender_id == CUSTOMER
    assert message.sender_name == "Ahmed Al Mansoori"
    assert message.text == "كم سعر قهوة كولومبية؟"
    assert message.received_at == datetime.fromtimestamp(TIMESTAMP, UTC)
    assert message.media == []


def test_image_with_caption(wa: WhatsAppCloud) -> None:
    body = webhook(
        {
            "contacts": [{"profile": {"name": "Sara"}, "wa_id": CUSTOMER}],
            "messages": [
                {
                    "from": CUSTOMER,
                    "id": "wamid.IMG1",
                    "timestamp": str(TIMESTAMP),
                    "type": "image",
                    "image": {
                        "caption": "هل عندكم هذا؟",
                        "mime_type": "image/jpeg",
                        "sha256": "abc",
                        "id": "MEDIA-ID-1",
                    },
                }
            ],
        }
    )
    (message,) = wa.parse_webhook(sign(body), body)
    assert message.text == "هل عندكم هذا؟"
    assert message.sender_name == "Sara"
    (media,) = message.media
    assert media.kind == "image"
    assert media.provider_id == "MEDIA-ID-1"
    assert media.mime_type == "image/jpeg"
    assert media.caption == "هل عندكم هذا؟"


def test_image_without_caption_gets_a_placeholder_text(wa: WhatsAppCloud) -> None:
    body = webhook(
        {
            "messages": [
                {
                    "from": CUSTOMER,
                    "id": "wamid.IMG2",
                    "timestamp": str(TIMESTAMP),
                    "type": "image",
                    "image": {"mime_type": "image/png", "id": "MEDIA-ID-2"},
                }
            ]
        }
    )
    (message,) = wa.parse_webhook(sign(body), body)
    assert message.text == "[image]"
    assert message.sender_name is None
    assert message.media[0].caption is None


def test_statuses_only_payload_yields_nothing(wa: WhatsAppCloud) -> None:
    body = webhook(
        {
            "statuses": [
                {
                    "id": "wamid.OUT1",
                    "status": "delivered",
                    "timestamp": str(TIMESTAMP),
                    "recipient_id": CUSTOMER,
                    "conversation": {"id": "conv-1", "origin": {"type": "service"}},
                    "pricing": {"billable": False, "pricing_model": "CBP", "category": "service"},
                }
            ]
        }
    )
    assert wa.parse_webhook(sign(body), body) == []


def test_message_with_user_id_instead_of_from(wa: WhatsAppCloud) -> None:
    body = webhook(
        {
            "contacts": [{"profile": {"name": "Layla", "username": "layla.k"}, "user_id": "BSUID-4711"}],
            "messages": [
                {
                    "user_id": "BSUID-4711",
                    "id": "wamid.BSUID1",
                    "timestamp": str(TIMESTAMP),
                    "text": {"body": "hello"},
                    "type": "text",
                }
            ],
        }
    )
    (message,) = wa.parse_webhook(sign(body), body)
    assert message.sender_id == "BSUID-4711"
    assert message.sender_name == "Layla"
    assert message.text == "hello"


def test_message_without_sender_or_id_is_skipped(wa: WhatsAppCloud) -> None:
    body = webhook(
        {
            "messages": [
                {"id": "wamid.NOSENDER", "timestamp": str(TIMESTAMP), "text": {"body": "x"}, "type": "text"},
                {"from": CUSTOMER, "timestamp": str(TIMESTAMP), "text": {"body": "y"}, "type": "text"},
                {
                    "from": CUSTOMER,
                    "id": "wamid.OK",
                    "timestamp": str(TIMESTAMP),
                    "text": {"body": "z"},
                    "type": "text",
                },
            ]
        }
    )
    messages = wa.parse_webhook(sign(body), body)
    assert [m.source_id for m in messages] == ["wamid.OK"]


def test_several_messages_in_one_webhook_keep_their_order(wa: WhatsAppCloud) -> None:
    body = webhook(
        {
            "messages": [
                {
                    "from": CUSTOMER,
                    "id": f"wamid.M{n}",
                    "timestamp": str(TIMESTAMP + n),
                    "text": {"body": str(n)},
                    "type": "text",
                }
                for n in range(3)
            ]
        }
    )
    assert [m.text for m in wa.parse_webhook(sign(body), body)] == ["0", "1", "2"]


def test_interactive_button_and_list_replies_use_the_title(wa: WhatsAppCloud) -> None:
    body = webhook(
        {
            "messages": [
                {
                    "from": CUSTOMER,
                    "id": "wamid.BTN",
                    "timestamp": str(TIMESTAMP),
                    "type": "interactive",
                    "interactive": {"type": "button_reply", "button_reply": {"id": "b1", "title": "نعم"}},
                },
                {
                    "from": CUSTOMER,
                    "id": "wamid.LST",
                    "timestamp": str(TIMESTAMP),
                    "type": "interactive",
                    "interactive": {"type": "list_reply", "list_reply": {"id": "l1", "title": "Grinders"}},
                },
                {
                    "from": CUSTOMER,
                    "id": "wamid.QR",
                    "timestamp": str(TIMESTAMP),
                    "type": "button",
                    "button": {"text": "Order"},
                },
            ]
        }
    )
    assert [m.text for m in wa.parse_webhook(sign(body), body)] == ["نعم", "Grinders", "Order"]


def test_unsupported_message_type_is_kept_as_a_marker(wa: WhatsAppCloud) -> None:
    body = webhook(
        {
            "messages": [
                {
                    "from": CUSTOMER,
                    "id": "wamid.LOC",
                    "timestamp": str(TIMESTAMP),
                    "type": "location",
                    "location": {"latitude": 25.2, "longitude": 55.3},
                }
            ]
        }
    )
    (message,) = wa.parse_webhook(sign(body), body)
    assert message.text == "[unsupported message type: location]"


def test_empty_object_payload_yields_nothing(wa: WhatsAppCloud) -> None:
    assert wa.parse_webhook(sign(b"{}"), b"{}") == []


def test_signed_but_malformed_json_is_a_value_error(wa: WhatsAppCloud) -> None:
    body = b"{not json"
    with pytest.raises(ValueError):
        wa.parse_webhook(sign(body), body)


# --- subscription handshake -----------------------------------------------------


def test_verify_subscription_returns_the_challenge(wa: WhatsAppCloud) -> None:
    params = {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1158201444"}
    assert wa.verify_subscription(params) == "1158201444"


def test_verify_subscription_refuses_a_wrong_token(wa: WhatsAppCloud) -> None:
    params = {"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1158201444"}
    assert wa.verify_subscription(params) is None


def test_verify_subscription_refuses_a_missing_token(wa: WhatsAppCloud) -> None:
    assert wa.verify_subscription({"hub.mode": "subscribe", "hub.challenge": "1"}) is None


def test_verify_subscription_refuses_a_wrong_mode(wa: WhatsAppCloud) -> None:
    params = {"hub.mode": "unsubscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1"}
    assert wa.verify_subscription(params) is None


def test_verify_subscription_non_ascii_token_is_refused_not_a_crash(wa: WhatsAppCloud) -> None:
    params = {"hub.mode": "subscribe", "hub.verify_token": "töken", "hub.challenge": "1"}
    assert wa.verify_subscription(params) is None


# --- the 24-hour window -----------------------------------------------------------


def test_freeform_allowed_inside_the_window(wa: WhatsAppCloud) -> None:
    assert wa.freeform_allowed(datetime.now(UTC) - timedelta(hours=23)) is True


def test_freeform_not_allowed_after_the_window(wa: WhatsAppCloud) -> None:
    assert wa.freeform_allowed(datetime.now(UTC) - timedelta(hours=25)) is False


def test_freeform_not_allowed_without_any_inbound_message(wa: WhatsAppCloud) -> None:
    assert wa.freeform_allowed(None) is False


# --- sending ---------------------------------------------------------------------------


async def test_send_text_posts_the_right_json(wa: WhatsAppCloud, mock_http: respx.MockRouter) -> None:
    route = mock_http.post(MESSAGES_URL).mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "wamid.SENT1"}]})
    )
    result = await wa.send_text(CUSTOMER, "السعر 135 درهم")

    assert result.provider_message_id == "wamid.SENT1"
    assert route.call_count == 1
    request = route.calls[0].request
    assert request.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert json.loads(request.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": CUSTOMER,
        "type": "text",
        "text": {"preview_url": False, "body": "السعر 135 درهم"},
    }


async def test_long_single_line_text_is_split_into_chunks_within_the_limit(
    wa: WhatsAppCloud, mock_http: respx.MockRouter
) -> None:
    text = "ب" * 9000
    ids = iter(["wamid.C1", "wamid.C2", "wamid.C3"])
    route = mock_http.post(MESSAGES_URL).mock(
        side_effect=lambda request: httpx.Response(200, json={"messages": [{"id": next(ids)}]})
    )
    result = await wa.send_text(CUSTOMER, text)

    bodies = [json.loads(call.request.content)["text"]["body"] for call in route.calls]
    assert len(bodies) == 3
    assert all(len(body) <= MAX_TEXT for body in bodies)
    assert "".join(bodies) == text
    assert result.provider_message_id == "wamid.C3"  # the id of the last chunk


async def test_long_multi_paragraph_text_splits_on_line_breaks(
    wa: WhatsAppCloud, mock_http: respx.MockRouter
) -> None:
    paragraphs = [f"{n}" * 1500 for n in range(1, 6)]
    text = "\n".join(paragraphs)
    route = mock_http.post(MESSAGES_URL).mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})
    )
    await wa.send_text(CUSTOMER, text)

    bodies = [json.loads(call.request.content)["text"]["body"] for call in route.calls]
    assert len(bodies) == 3
    assert all(len(body) <= MAX_TEXT for body in bodies)
    assert "\n".join(bodies) == text  # nothing lost, and paragraphs are never cut in half


async def test_text_exactly_at_the_limit_is_one_message(
    wa: WhatsAppCloud, mock_http: respx.MockRouter
) -> None:
    route = mock_http.post(MESSAGES_URL).mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})
    )
    await wa.send_text(CUSTOMER, "a" * MAX_TEXT)
    assert route.call_count == 1


async def test_send_text_http_500_is_retryable(wa: WhatsAppCloud, mock_http: respx.MockRouter) -> None:
    mock_http.post(MESSAGES_URL).mock(return_value=httpx.Response(500, json={"error": {"message": "oops"}}))
    with pytest.raises(IntegrationError) as caught:
        await wa.send_text(CUSTOMER, "hi")
    assert caught.value.retryable is True


async def test_send_text_http_429_is_retryable(wa: WhatsAppCloud, mock_http: respx.MockRouter) -> None:
    mock_http.post(MESSAGES_URL).mock(
        return_value=httpx.Response(429, json={"error": {"message": "slow down"}})
    )
    with pytest.raises(IntegrationError) as caught:
        await wa.send_text(CUSTOMER, "hi")
    assert caught.value.retryable is True


async def test_send_text_http_400_is_not_retryable(wa: WhatsAppCloud, mock_http: respx.MockRouter) -> None:
    mock_http.post(MESSAGES_URL).mock(
        return_value=httpx.Response(400, json={"error": {"message": "bad number"}})
    )
    with pytest.raises(IntegrationError) as caught:
        await wa.send_text(CUSTOMER, "hi")
    assert caught.value.retryable is False


async def test_send_text_network_error_is_retryable(wa: WhatsAppCloud, mock_http: respx.MockRouter) -> None:
    mock_http.post(MESSAGES_URL).mock(side_effect=httpx.ConnectError("no route"))
    with pytest.raises(IntegrationError) as caught:
        await wa.send_text(CUSTOMER, "hi")
    assert caught.value.retryable is True
