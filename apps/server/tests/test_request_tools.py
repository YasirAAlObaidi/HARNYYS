"""create_quote_request and handover_to_staff: what they record, and the guards around them."""

from __future__ import annotations

import json
from typing import Any

import psycopg
import pytest
from pydantic import ValidationError

from yyai.core.types import CatalogueItem, RunContext
from yyai.handlers.persistence.db import Database
from yyai.handlers.persistence.requests import RequestStore
from yyai.services.requests import MAX_OPEN_QUOTE_REQUESTS, RequestService
from yyai.workflows.agent.registry import Tool
from yyai.workflows.agent.request_tools import CreateQuoteRequestArgs, HandoverArgs, build_request_tools

ITEMS = {
    "ETH-1KG": CatalogueItem(
        code="ETH-1KG", name_en="Ethiopia Yirgacheffe 1 kg", attributes={"unit": "kg"}, price=None
    ),
    "CBR-101": CatalogueItem(code="CBR-101", name_en="Gene Cafe CBR-101 roaster", attributes={}),
}


class FakeCatalogue:
    """Only products on sale are in the copy, so get() is the 'exists and active' check."""

    async def get(self, code: str) -> CatalogueItem | None:
        return ITEMS.get(code)


def ctx(conversation_id: int, turn_id: int | None = None, channel: str = "whatsapp") -> RunContext:
    return RunContext(
        turn_id=turn_id or 0,
        conversation_id=conversation_id,
        channel=channel,
        customer_id="971500000000",
        customer_name=None,
        client_name="Kahraman",
        currency="AED",
        auto_send=True,
    )


def tools(db: Database) -> dict[str, Tool]:
    built = build_request_tools(FakeCatalogue(), RequestService(RequestStore(db)))  # type: ignore[arg-type]
    return {tool.name: tool for tool in built}


async def call(tool: Tool, context: RunContext, **args: Any) -> dict[str, Any]:
    result = await tool.fn(context, tool.args_model(**args))
    json.dumps(result)
    return result


def chat(sql: psycopg.Connection, user: str = "971500000000") -> tuple[int, int]:
    conversation = sql.execute(
        "INSERT INTO conversations (channel, external_user_id) VALUES ('whatsapp', %s) RETURNING id", (user,)
    ).fetchone()["id"]
    turn = sql.execute(
        "INSERT INTO turns (conversation_id, state) VALUES (%s, 'running') RETURNING id", (conversation,)
    ).fetchone()["id"]
    return conversation, turn


# --- no database needed ---------------------------------------------------------------------------------------


def test_no_argument_can_name_a_customer_or_a_chat() -> None:
    for model in (CreateQuoteRequestArgs, HandoverArgs):
        fields = set(model.model_fields)
        assert not fields & {"customer", "customer_id", "phone", "conversation_id", "to", "user_id"}, fields


def test_bad_arguments_are_rejected_before_anything_runs() -> None:
    for bad in (
        {"quantity": 0},
        {"quantity": -2},
        {"quantity": 10_001},
        {"area": "x" * 101},
        {"note": "x" * 201},
    ):
        with pytest.raises(ValidationError):
            CreateQuoteRequestArgs(**{"code": "ETH-1KG", "quantity": 5, **bad})
    with pytest.raises(ValidationError):
        HandoverArgs(reason="bored", summary="x")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        HandoverArgs(reason="complaint", summary="x" * 201)


# --- with the database ----------------------------------------------------------------------------------------


@pytest.mark.db
async def test_a_quote_request_is_saved_for_this_chat(db: Database, sql: psycopg.Connection) -> None:
    conversation, turn = chat(sql)
    result = await call(
        tools(db)["create_quote_request"], ctx(conversation, turn),
        code="ETH-1KG", quantity=20, area="  Al   Quoz ", note="for a café opening",
    )  # fmt: skip

    assert (result["ok"], result["saved"], result["updated_existing"]) == (True, True, False)
    assert (result["product"], result["quantity"], result["unit"], result["area"]) == (
        "Ethiopia Yirgacheffe 1 kg",
        20,
        "kg",
        "Al Quoz",
    )
    row = sql.execute("SELECT * FROM quote_requests").fetchone()
    assert (row["conversation_id"], row["turn_id"], row["code"], row["status"]) == (
        conversation,
        turn,
        "ETH-1KG",
        "open",
    )
    assert row["note"] == "for a café opening"


@pytest.mark.db
async def test_asking_again_for_the_same_product_updates_the_open_request(
    db: Database, sql: psycopg.Connection
) -> None:
    conversation, turn = chat(sql)
    quote = tools(db)["create_quote_request"]
    await call(quote, ctx(conversation, turn), code="ETH-1KG", quantity=20, area="Al Quoz")
    again = await call(quote, ctx(conversation, turn), code="ETH-1KG", quantity=25)
    await call(quote, ctx(conversation, turn), code="CBR-101", quantity=1)

    assert again["updated_existing"] is True
    rows = sql.execute("SELECT code, quantity, area FROM quote_requests ORDER BY code").fetchall()
    assert [(r["code"], float(r["quantity"]), r["area"]) for r in rows] == [
        ("CBR-101", 1.0, None),
        ("ETH-1KG", 25.0, "Al Quoz"),  # the area given earlier is kept
    ]


@pytest.mark.db
async def test_an_unknown_or_switched_off_product_is_refused(db: Database, sql: psycopg.Connection) -> None:
    conversation, turn = chat(sql)
    result = await call(
        tools(db)["create_quote_request"], ctx(conversation, turn), code="MADE-UP", quantity=3
    )

    assert result["ok"] is False
    assert "quote_price" in result["error"]
    assert sql.execute("SELECT count(*) AS n FROM quote_requests").fetchone()["n"] == 0


@pytest.mark.db
async def test_a_chat_cannot_pile_up_quote_requests(db: Database, sql: psycopg.Connection) -> None:
    conversation, turn = chat(sql)
    for n in range(MAX_OPEN_QUOTE_REQUESTS):
        sql.execute(
            "INSERT INTO quote_requests (conversation_id, code, product_name, quantity) VALUES (%s, %s, 'x', 1)",
            (conversation, f"CODE-{n}"),
        )
    result = await call(
        tools(db)["create_quote_request"], ctx(conversation, turn), code="ETH-1KG", quantity=1
    )

    assert result["ok"] is False
    assert "handover" in result["error"]


@pytest.mark.db
async def test_a_handover_is_saved_once_per_chat(db: Database, sql: psycopg.Connection) -> None:
    conversation, turn = chat(sql)
    other, other_turn = chat(sql, "971509999999")
    handover = tools(db)["handover_to_staff"]
    first = await call(
        handover, ctx(conversation, turn), reason="missing_price", summary="Wants the 1 kg price."
    )
    second = await call(handover, ctx(conversation, turn), reason="complaint", summary="Now upset.")
    await call(handover, ctx(other, other_turn), reason="asked_for_human", summary="Asked for Ahmed.")

    assert (first["already_with_staff"], second["already_with_staff"]) == (False, True)
    rows = sql.execute(
        "SELECT conversation_id, reason, summary, source FROM handovers ORDER BY id"
    ).fetchall()
    assert [(r["conversation_id"], r["reason"], r["summary"], r["source"]) for r in rows] == [
        (conversation, "missing_price", "Wants the 1 kg price.", "tool"),
        (other, "asked_for_human", "Asked for Ahmed.", "tool"),
    ]


@pytest.mark.db
async def test_staff_test_chats_record_nothing(db: Database, sql: psycopg.Connection) -> None:
    conversation, turn = chat(sql)
    staff = ctx(conversation, turn, channel="staff")
    by_name = tools(db)
    quote = await call(by_name["create_quote_request"], staff, code="ETH-1KG", quantity=5)
    handover = await call(by_name["handover_to_staff"], staff, reason="other", summary="Testing.")

    assert quote["saved"] is False and handover["saved"] is False
    assert sql.execute("SELECT count(*) AS n FROM quote_requests").fetchone()["n"] == 0
    assert sql.execute("SELECT count(*) AS n FROM handovers").fetchone()["n"] == 0
