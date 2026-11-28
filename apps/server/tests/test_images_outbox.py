"""Images in the outbox: text first, then pictures; the turn is 'sent' only when every row is."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from yyai.core.types import InboundMessage, OutboundImage
from yyai.handlers.persistence.conversations import ConversationStore
from yyai.handlers.persistence.db import Database

pytestmark = pytest.mark.db

IMAGES = [OutboundImage(url=f"https://img.test/{n}.jpg", caption=f"*P{n}*") for n in range(3)]


@pytest.fixture
def store(db: Database) -> ConversationStore:
    return ConversationStore(db)


async def queue(store: ConversationStore, *, auto_send: bool = True) -> int:
    await store.record_inbound(
        InboundMessage(
            channel="whatsapp", source_id="w1", sender_id="971500000000", text="hi", received_at=datetime.now(UTC)
        )
    )
    turn = await store.claim_turn()
    assert turn is not None
    await store.finish_turn(turn.id, turn.conversation_id, "reply", auto_send=auto_send, steps=1, images=IMAGES)
    return turn.id


def rows(sql: psycopg.Connection) -> list[dict[str, Any]]:
    return sql.execute("SELECT id, kind, text, image_url, status FROM outbox ORDER BY id").fetchall()


async def test_text_row_comes_first_then_one_row_per_image(store: ConversationStore, sql: psycopg.Connection) -> None:
    await queue(store)
    got = rows(sql)
    assert [(r["kind"], r["image_url"]) for r in got] == [("text", None)] + [("image", i.url) for i in IMAGES]
    assert got[1]["text"] == "*P0*"
    assert {r["status"] for r in got} == {"pending"}
    assert sql.execute("SELECT count(*) AS n FROM messages WHERE direction = 'out'").fetchone()["n"] == 1


async def test_rows_are_claimed_in_order_and_the_turn_is_sent_only_after_all(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    turn_id = await queue(store)
    sent_kinds = []
    for n in range(4):
        record = await store.claim_outbox()
        assert record is not None
        sent_kinds.append(record.kind)
        # While a row of the turn is in flight, nothing later in the turn may be claimed.
        assert await store.claim_outbox() is None
        await store.mark_sent(record.id, record.turn_id, f"id{n}")
        state = sql.execute("SELECT state FROM turns WHERE id = %s", (turn_id,)).fetchone()["state"]
        assert state == ("sent" if n == 3 else "sending")
    assert sent_kinds == ["text", "image", "image", "image"]


async def test_a_retrying_text_row_holds_back_the_images(store: ConversationStore, sql: psycopg.Connection) -> None:
    await queue(store)
    record = await store.claim_outbox()
    assert record is not None
    await store.mark_send_failed(record.id, record.turn_id, "503", datetime.now(UTC).replace(year=2099))
    assert await store.claim_outbox() is None


async def test_a_text_that_fails_for_good_cancels_its_images(store: ConversationStore, sql: psycopg.Connection) -> None:
    turn_id = await queue(store)
    record = await store.claim_outbox()
    assert record is not None
    await store.mark_send_failed(record.id, record.turn_id, "window closed", None)
    assert {r["status"] for r in rows(sql)} == {"failed"}
    assert sql.execute("SELECT state FROM turns WHERE id = %s", (turn_id,)).fetchone()["state"] == "failed"
    assert await store.claim_outbox() is None


async def test_a_lost_image_does_not_fail_a_turn_whose_text_was_sent(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    turn_id = await queue(store)
    text = await store.claim_outbox()
    assert text is not None
    await store.mark_sent(text.id, text.turn_id, "t")
    for n in range(3):
        image = await store.claim_outbox()
        assert image is not None
        if n == 1:
            await store.mark_send_failed(image.id, image.turn_id, "bad image", None)
        else:
            await store.mark_sent(image.id, image.turn_id, f"i{n}")
    assert sql.execute("SELECT state FROM turns WHERE id = %s", (turn_id,)).fetchone()["state"] == "sent"


async def test_approval_mode_queues_all_rows_awaiting_approval(store: ConversationStore, sql: psycopg.Connection) -> None:
    await queue(store, auto_send=False)
    assert {r["status"] for r in rows(sql)} == {"awaiting_approval"}
