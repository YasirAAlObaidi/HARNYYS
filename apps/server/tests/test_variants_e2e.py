# ruff: noqa: F811  (make_env is a fixture imported from test_end_to_end)
"""A general question lists base products once (no colours) and queues their pictures; a pick offers the options."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import httpx
import pytest
import respx
from test_end_to_end import (
    MODEL_URL,
    Env,
    completion,
    make_env,  # noqa: F401  (a fixture)
    whatsapp_body,
)

pytestmark = pytest.mark.db


def call(name: str, **args: object) -> dict:
    return {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


async def variant_env(make_env: Callable[..., Awaitable[Env]], variant_catalogue) -> Env:
    env: Env = await make_env()
    env.catalogue_path.write_text(variant_catalogue.read_text(encoding="utf-8"), encoding="utf-8")
    await env.workflows.catalogue_sync.run()
    return env


async def tool_results(model: respx.Route) -> list[object]:
    request = json.loads(model.calls[-1].request.content)
    return [json.loads(m["content"]) for m in request["messages"] if m["role"] == "tool"]


async def test_general_listing_has_no_variant_names_and_queues_images(
    make_env, variant_catalogue, mock_http: respx.MockRouter
) -> None:
    env = await variant_env(make_env, variant_catalogue)
    await env.post_whatsapp(whatsapp_body("How much is a coffee grinder", "wamid.G1"))
    model = mock_http.post(MODEL_URL).mock(
        side_effect=[
            httpx.Response(200, json=completion(tool_calls=[call("search_products", query="coffee grinder", limit=5)])),
            httpx.Response(200, json=completion("**F5** from AED 1,600, F64 AED 8,000, VBM Lollo from AED 12,000")),
        ]
    )
    assert await env.workflows.turns.run_once() is True

    (result,) = await tool_results(model)
    names = [r["name_en"] for r in result]
    assert len(names) == len(set(names))
    assert "Fiorenzato F5 Coffee Grinder" in names
    text = json.dumps(result, ensure_ascii=False)
    for word in ("Black", "White", "Red", "Groups", "أسود", "color"):
        assert word not in text
    f5 = next(r for r in result if r["name_en"] == "Fiorenzato F5 Coffee Grinder")
    assert (f5["has_variants"], f5["code"]) == (True, "f5-grinder")
    assert "price" not in f5  # prices come from quote_price only

    rows = env.sql.execute("SELECT kind, text, image_url, status FROM outbox ORDER BY id").fetchall()
    assert rows[0]["kind"] == "text"
    images = rows[1:]
    assert 1 <= len(images) <= 3
    assert all(r["kind"] == "image" and r["image_url"].startswith("https://img.test/") for r in images)
    assert not any(r["image_url"].endswith(".webp") for r in images)  # WhatsApp takes JPEG and PNG only
    assert images[0]["text"].startswith("*") and "AED" in images[0]["text"]


async def test_quote_without_a_choice_asks_for_one_and_a_named_option_is_quoted(
    make_env, variant_catalogue, mock_http: respx.MockRouter
) -> None:
    env = await variant_env(make_env, variant_catalogue)
    await env.post_whatsapp(whatsapp_body("the Fiorenzato F5", "wamid.G2"))
    model = mock_http.post(MODEL_URL).mock(
        side_effect=[
            httpx.Response(200, json=completion(tool_calls=[call("quote_price", query="Fiorenzato F5")])),
            httpx.Response(200, json=completion("Which colour: Black, White or Red?")),
        ]
    )
    await env.workflows.turns.run_once()
    (quote,) = await tool_results(model)
    assert quote["needs_choice"] is True
    assert quote["name_en"] == "Fiorenzato F5 Coffee Grinder"
    assert [o["label"] for o in quote["options"]] == ["Black", "Red", "White"] or {o["label"] for o in quote["options"]} == {"Black", "White", "Red"}
    images = env.sql.execute("SELECT image_url FROM outbox WHERE kind = 'image'").fetchall()
    assert len(images) == 1

    # The customer picks red: that exact variant is quoted, with its own picture.
    env.sql.execute("DELETE FROM outbox")
    await env.post_whatsapp(whatsapp_body("red please", "wamid.G3"))
    model2 = mock_http.post(MODEL_URL).mock(
        side_effect=[
            httpx.Response(200, json=completion(tool_calls=[call("quote_price", query="Fiorenzato F5 Coffee Grinder red")])),
            httpx.Response(200, json=completion("The red one is AED 1,700")),
        ]
    )
    await env.workflows.turns.run_once()
    (red,) = await tool_results(model2)
    assert red["code"] == "f5-grinder-red" and red["price"] == 1700 and "needs_choice" not in red
    image = env.sql.execute("SELECT image_url, text FROM outbox WHERE kind = 'image'").fetchone()
    assert image["image_url"] == "https://img.test/f5-red.jpg"
    assert "AED 1,700" in image["text"]


async def test_product_details_of_a_base_product_lists_the_options(
    make_env, variant_catalogue, mock_http: respx.MockRouter
) -> None:
    env = await variant_env(make_env, variant_catalogue)
    await env.post_whatsapp(whatsapp_body("tell me about the F5", "wamid.G4"))
    model = mock_http.post(MODEL_URL).mock(
        side_effect=[
            httpx.Response(200, json=completion(tool_calls=[call("product_details", code="f5-grinder")])),
            httpx.Response(200, json=completion("Options: Black, White, Red")),
        ]
    )
    await env.workflows.turns.run_once()
    (details,) = await tool_results(model)
    assert details["has_variants"] is True
    assert {o["label"] for o in details["options"]} == {"Black", "White", "Red"}
    assert "color" not in details["attributes"]
