"""ConversationStore against a real Postgres: dedupe, the one-turn-per-conversation lock, the outbox, recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from yyai.core.types import Direction, InboundMessage, MediaRef
from yyai.handlers.persistence.conversations import ConversationStore
from yyai.handlers.persistence.db import Database

pytestmark = pytest.mark.db

ALICE = "971501111111"
BOB = "971502222222"


@pytest.fixture
def store(db: Database) -> ConversationStore:
    return ConversationStore(db)


def inbound(
    source_id: str,
    *,
    sender: str = ALICE,
    text: str = "hello",
    name: str | None = None,
    at: datetime | None = None,
    channel: str = "whatsapp",
) -> InboundMessage:
    return InboundMessage(
        channel=channel,
        source_id=source_id,
        sender_id=sender,
        sender_name=name,
        text=text,
        received_at=at or datetime.now(UTC),
    )


def rows(sql: psycopg.Connection, query: str, *params: Any) -> list[dict[str, Any]]:
    return sql.execute(query, params).fetchall()


def one(sql: psycopg.Connection, query: str, *params: Any) -> dict[str, Any]:
    result = rows(sql, query, *params)
    assert len(result) == 1, f"expected one row, got {len(result)}: {result}"
    return result[0]


def count(sql: psycopg.Connection, table: str, where: str = "true") -> int:
    return one(sql, f"SELECT count(*) AS n FROM {table} WHERE {where}")["n"]


# --- record_inbound -------------------------------------------------------------------------------


async def test_record_inbound_creates_conversation_message_and_waiting_turn(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    conversation_id, is_new = await store.record_inbound(inbound("wamid.1", text="كم السعر؟", name="Alice"))

    assert is_new is True
    conversation = one(sql, "SELECT * FROM conversations")
    assert conversation["id"] == conversation_id
    assert (conversation["channel"], conversation["external_user_id"], conversation["customer_name"]) == (
        "whatsapp", ALICE, "Alice",
    )  # fmt: skip
    message = one(sql, "SELECT * FROM messages")
    assert (message["direction"], message["source_id"], message["text"]) == ("in", "wamid.1", "كم السعر؟")
    turn = one(sql, "SELECT * FROM turns")
    assert (turn["conversation_id"], turn["state"]) == (conversation_id, "received")


async def test_record_inbound_dedupes_the_same_source_id(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    first_id, first_new = await store.record_inbound(inbound("wamid.1"))
    second_id, second_new = await store.record_inbound(inbound("wamid.1"))

    assert (first_new, second_new) == (True, False)
    assert first_id == second_id
    assert count(sql, "messages") == 1
    assert count(sql, "turns") == 1
    assert count(sql, "conversations") == 1


async def test_a_redelivered_message_after_its_turn_finished_queues_nothing(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    await store.record_inbound(inbound("wamid.1"))
    turn = await store.claim_turn()
    assert turn is not None
    await store.finish_turn(turn.id, turn.conversation_id, "hi", auto_send=True, steps=1)

    _, is_new = await store.record_inbound(inbound("wamid.1"))

    assert is_new is False
    assert count(sql, "turns") == 1
    assert count(sql, "turns", "state = 'received'") == 0


async def test_two_quick_messages_in_one_conversation_create_one_waiting_turn(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    _, first_new = await store.record_inbound(inbound("wamid.1", text="سلام"))
    _, second_new = await store.record_inbound(inbound("wamid.2", text="كم سعر القهوة؟"))

    assert (first_new, second_new) == (True, True)
    assert count(sql, "messages") == 2
    assert count(sql, "turns") == 1
    assert count(sql, "turns", "state = 'received'") == 1


async def test_different_customers_get_their_own_conversation_and_turn(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    await store.record_inbound(inbound("wamid.1", sender=ALICE))
    await store.record_inbound(inbound("wamid.2", sender=BOB))
    assert count(sql, "conversations") == 2
    assert count(sql, "turns") == 2


async def test_same_user_on_another_channel_is_a_separate_conversation(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    await store.record_inbound(inbound("m1", sender=ALICE, channel="whatsapp"))
    await store.record_inbound(inbound("m1", sender=ALICE, channel="webchat"))
    assert count(sql, "conversations") == 2
    assert count(sql, "messages") == 2


async def test_conversation_keeps_a_known_name_and_never_moves_last_inbound_back(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    await store.record_inbound(inbound("wamid.1", name="Alice", at=now))
    await store.record_inbound(
        inbound("wamid.2", name=None, at=now - timedelta(hours=1))
    )  # late, older message

    conversation = one(sql, "SELECT customer_name, last_inbound_at FROM conversations")
    assert conversation["customer_name"] == "Alice"
    assert conversation["last_inbound_at"] == now


async def test_media_is_stored_as_json(store: ConversationStore, sql: psycopg.Connection) -> None:
    message = inbound("wamid.img", text="هل عندكم هذا؟")
    message.media = [
        MediaRef(kind="image", provider_id="MEDIA-1", mime_type="image/jpeg", caption="هل عندكم هذا؟")
    ]
    await store.record_inbound(message)
    stored = one(sql, "SELECT media FROM messages")["media"]
    assert stored[0]["kind"] == "image"
    assert stored[0]["provider_id"] == "MEDIA-1"


# --- claim_turn -------------------------------------------------------------------------------------


async def test_claim_turn_returns_none_when_nothing_is_waiting(store: ConversationStore) -> None:
    assert await store.claim_turn() is None


async def test_claim_turn_marks_it_running_and_returns_the_context(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    conversation_id, _ = await store.record_inbound(inbound("wamid.1", name="Alice"))
    turn = await store.claim_turn()

    assert turn is not None
    assert turn.conversation_id == conversation_id
    assert (turn.channel, turn.external_user_id, turn.customer_name, turn.attempts) == (
        "whatsapp",
        ALICE,
        "Alice",
        1,
    )
    row = one(sql, "SELECT state, attempts, started_at FROM turns WHERE id = %s", turn.id)
    assert row["state"] == "running"
    assert row["attempts"] == 1
    assert row["started_at"] is not None
    assert await store.claim_turn() is None  # the same turn is never handed out twice


async def test_claim_turn_returns_none_while_the_conversation_already_has_a_running_turn(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    await store.record_inbound(inbound("wamid.1"))
    first = await store.claim_turn()
    assert first is not None

    await store.record_inbound(inbound("wamid.2", text="and one more thing"))  # queues a second waiting turn
    assert count(sql, "turns", "state = 'received'") == 1
    assert await store.claim_turn() is None  # blocked: the conversation is busy

    await store.finish_turn(first.id, first.conversation_id, "reply", auto_send=True, steps=1)
    second = await store.claim_turn()
    assert second is not None
    assert second.id != first.id
    assert second.conversation_id == first.conversation_id


async def test_a_running_turn_in_one_conversation_does_not_block_another(store: ConversationStore) -> None:
    await store.record_inbound(inbound("wamid.1", sender=ALICE))
    await store.record_inbound(inbound("wamid.2", sender=BOB))
    first = await store.claim_turn()
    second = await store.claim_turn()
    assert first is not None and second is not None
    assert {first.external_user_id, second.external_user_id} == {ALICE, BOB}


async def test_turns_are_claimed_oldest_first(store: ConversationStore) -> None:
    await store.record_inbound(inbound("wamid.1", sender=ALICE))
    await store.record_inbound(inbound("wamid.2", sender=BOB))
    first = await store.claim_turn()
    assert first is not None
    assert first.external_user_id == ALICE


# --- finish_turn ----------------------------------------------------------------------------------------


async def test_finish_turn_with_auto_send_queues_a_pending_outbox_row(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    await store.record_inbound(inbound("wamid.1"))
    turn = await store.claim_turn()
    assert turn is not None

    await store.finish_turn(turn.id, turn.conversation_id, "السعر ١٣٥ درهم", auto_send=True, steps=2)

    message = one(sql, "SELECT * FROM messages WHERE direction = 'out'")
    assert message["text"] == "السعر ١٣٥ درهم"
    assert message["turn_id"] == turn.id
    assert message["source_id"] is None
    outbox = one(sql, "SELECT * FROM outbox")
    assert (outbox["status"], outbox["text"], outbox["turn_id"], outbox["message_id"]) == (
        "pending", "السعر ١٣٥ درهم", turn.id, message["id"],
    )  # fmt: skip
    state = one(sql, "SELECT state, steps, finished_at FROM turns WHERE id = %s", turn.id)
    assert state["state"] == "sending"
    assert state["steps"] == 2
    assert state["finished_at"] is not None


async def test_finish_turn_without_auto_send_waits_for_approval(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    await store.record_inbound(inbound("wamid.1"))
    turn = await store.claim_turn()
    assert turn is not None

    await store.finish_turn(turn.id, turn.conversation_id, "draft reply", auto_send=False, steps=1)

    outbox = one(sql, "SELECT * FROM outbox")
    assert outbox["status"] == "awaiting_approval"
    assert one(sql, "SELECT state FROM turns")["state"] == "sending"
    assert await store.claim_outbox() is None  # nothing is sent until staff approve

    assert await store.approve_outbox(outbox["id"]) is True
    assert await store.approve_outbox(outbox["id"]) is False  # already released
    claimed = await store.claim_outbox()
    assert claimed is not None
    assert claimed.text == "draft reply"


async def test_approve_unknown_outbox_id_is_false(store: ConversationStore) -> None:
    assert await store.approve_outbox(12345) is False


async def test_finish_turn_without_a_reply_just_closes_the_turn(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    await store.record_inbound(inbound("wamid.1"))
    turn = await store.claim_turn()
    assert turn is not None

    await store.finish_turn(turn.id, turn.conversation_id, None, auto_send=True, steps=1)

    assert one(sql, "SELECT state FROM turns")["state"] == "done"
    assert count(sql, "outbox") == 0
    assert count(sql, "messages", "direction = 'out'") == 0


# --- outbox -------------------------------------------------------------------------------------------------


async def _queue_reply(store: ConversationStore, *, text: str = "reply", at: datetime | None = None) -> int:
    """Receive a message, run its turn and return the turn id, leaving one pending outbox row."""
    await store.record_inbound(inbound("wamid.in", at=at))
    turn = await store.claim_turn()
    assert turn is not None
    await store.finish_turn(turn.id, turn.conversation_id, text, auto_send=True, steps=1)
    return turn.id


async def test_claim_outbox_returns_the_send_context_and_marks_it_sending(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    at = datetime.now(UTC).replace(microsecond=0)
    turn_id = await _queue_reply(store, text="hello back", at=at)

    record = await store.claim_outbox()

    assert record is not None
    assert (record.channel, record.to, record.text, record.turn_id, record.attempts) == (
        "whatsapp", ALICE, "hello back", turn_id, 1,
    )  # fmt: skip
    assert record.last_inbound_at == at
    row = one(sql, "SELECT status, claimed_at FROM outbox")
    assert row["status"] == "sending"
    assert row["claimed_at"] is not None
    assert await store.claim_outbox() is None


async def test_mark_sent_finishes_the_outbox_row_and_the_turn(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    turn_id = await _queue_reply(store)
    record = await store.claim_outbox()
    assert record is not None

    await store.mark_sent(record.id, record.turn_id, "wamid.OUT")

    outbox = one(sql, "SELECT status, provider_message_id, sent_at, last_error FROM outbox")
    assert outbox["status"] == "sent"
    assert outbox["provider_message_id"] == "wamid.OUT"
    assert outbox["sent_at"] is not None
    assert one(sql, "SELECT state FROM turns WHERE id = %s", turn_id)["state"] == "sent"


async def test_mark_send_failed_with_retry_at_requeues_for_later(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    turn_id = await _queue_reply(store)
    record = await store.claim_outbox()
    assert record is not None
    retry_at = datetime.now(UTC) + timedelta(hours=1)

    await store.mark_send_failed(record.id, record.turn_id, "HTTP 503", retry_at)

    outbox = one(sql, "SELECT status, last_error, next_attempt_at FROM outbox")
    assert outbox["status"] == "pending"
    assert outbox["last_error"] == "HTTP 503"
    assert abs((outbox["next_attempt_at"] - retry_at).total_seconds()) < 1
    assert one(sql, "SELECT state FROM turns WHERE id = %s", turn_id)["state"] == "sending"  # not failed
    assert await store.claim_outbox() is None  # not due yet

    sql.execute("UPDATE outbox SET next_attempt_at = now() - interval '1 second'")
    again = await store.claim_outbox()
    assert again is not None
    assert again.attempts == 2


async def test_mark_send_failed_without_retry_at_fails_the_row_and_the_turn(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    turn_id = await _queue_reply(store)
    record = await store.claim_outbox()
    assert record is not None

    await store.mark_send_failed(record.id, record.turn_id, "bad phone number", None)

    outbox = one(sql, "SELECT status, last_error FROM outbox")
    assert (outbox["status"], outbox["last_error"]) == ("failed", "bad phone number")
    turn = one(sql, "SELECT state, error FROM turns WHERE id = %s", turn_id)
    assert turn["state"] == "failed"
    assert "bad phone number" in turn["error"]
    assert await store.claim_outbox() is None


# --- fail_turn, audit, history, views ---------------------------------------------------------------------------


async def test_fail_turn_records_the_error_and_cuts_it_to_2000_characters(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    await store.record_inbound(inbound("wamid.1"))
    turn = await store.claim_turn()
    assert turn is not None
    await store.fail_turn(turn.id, "x" * 5000)
    row = one(sql, "SELECT state, error, finished_at FROM turns")
    assert row["state"] == "failed"
    assert len(row["error"]) == 2000
    assert row["finished_at"] is not None


async def test_audit_stores_structured_data_with_arabic_intact(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    await store.record_inbound(inbound("wamid.1"))
    turn = await store.claim_turn()
    assert turn is not None
    await store.audit(turn.id, "tool_call", "quote_price", {"args": {"query": "قهوة"}, "n": 1})
    await store.audit(None, "note", None, {})

    first, second = rows(sql, "SELECT * FROM audit_log ORDER BY id")
    assert (first["turn_id"], first["kind"], first["name"]) == (turn.id, "tool_call", "quote_price")
    assert first["data"] == {"args": {"query": "قهوة"}, "n": 1}
    assert (second["turn_id"], second["name"], second["data"]) == (None, None, {})


async def test_history_returns_the_latest_messages_oldest_first(store: ConversationStore) -> None:
    conversation_id = 0
    for n in range(1, 6):
        conversation_id, _ = await store.record_inbound(inbound(f"wamid.{n}", text=f"message {n}"))

    history = await store.history(conversation_id, limit=3)

    assert [m.text for m in history] == ["message 3", "message 4", "message 5"]
    assert all(m.direction == Direction.INBOUND for m in history)


async def test_history_includes_our_replies_as_outbound(store: ConversationStore) -> None:
    await store.record_inbound(inbound("wamid.1", text="hi"))
    turn = await store.claim_turn()
    assert turn is not None
    await store.finish_turn(turn.id, turn.conversation_id, "hello!", auto_send=True, steps=1)

    history = await store.history(turn.conversation_id, limit=10)

    assert [(m.direction, m.text) for m in history] == [
        (Direction.INBOUND, "hi"),
        (Direction.OUTBOUND, "hello!"),
    ]


async def test_list_conversations_newest_activity_first(store: ConversationStore) -> None:
    now = datetime.now(UTC)
    await store.record_inbound(inbound("wamid.1", sender=ALICE, name="Alice", at=now - timedelta(minutes=5)))
    await store.record_inbound(inbound("wamid.2", sender=BOB, name="Bob", at=now))

    conversations = await store.list_conversations(10)

    assert [c.customer_name for c in conversations] == ["Bob", "Alice"]
    assert len(await store.list_conversations(1)) == 1


async def test_ping(store: ConversationStore) -> None:
    assert await store.ping() is True


# --- recover_stale ----------------------------------------------------------------------------------------------------


async def test_recover_stale_requeues_an_old_running_turn(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    await store.record_inbound(inbound("wamid.1"))
    turn = await store.claim_turn()
    assert turn is not None
    sql.execute("UPDATE turns SET started_at = now() - interval '2 hours' WHERE id = %s", (turn.id,))

    assert await store.recover_stale(900) == 1

    assert one(sql, "SELECT state FROM turns WHERE id = %s", turn.id)["state"] == "received"
    again = await store.claim_turn()
    assert again is not None
    assert again.id == turn.id
    assert again.attempts == 2


async def test_recover_stale_leaves_a_recent_running_turn_alone(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    await store.record_inbound(inbound("wamid.1"))
    turn = await store.claim_turn()
    assert turn is not None
    sql.execute("UPDATE turns SET started_at = now() - interval '5 minutes' WHERE id = %s", (turn.id,))

    assert await store.recover_stale(900) == 0

    assert one(sql, "SELECT state FROM turns")["state"] == "running"


async def test_recover_stale_gives_up_on_a_turn_that_keeps_crashing_the_worker(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    await store.record_inbound(inbound("wamid.1"))
    turn = await store.claim_turn()
    assert turn is not None
    sql.execute(
        "UPDATE turns SET started_at = now() - interval '2 hours', attempts = 3 WHERE id = %s", (turn.id,)
    )

    assert await store.recover_stale(900, max_attempts=3) == 1

    row = one(sql, "SELECT state, error FROM turns")
    assert row["state"] == "failed"
    assert "too often" in row["error"]


async def test_recover_stale_fails_an_old_running_turn_when_a_newer_message_is_already_waiting(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    # Re-queueing it would put two waiting turns in one conversation, which the schema forbids.
    await store.record_inbound(inbound("wamid.1"))
    stale = await store.claim_turn()
    assert stale is not None
    await store.record_inbound(inbound("wamid.2"))
    sql.execute("UPDATE turns SET started_at = now() - interval '2 hours' WHERE id = %s", (stale.id,))

    assert await store.recover_stale(900) == 1

    assert one(sql, "SELECT state FROM turns WHERE id = %s", stale.id)["state"] == "failed"
    waiting = await store.claim_turn()  # the newer message is still answered, with the full history
    assert waiting is not None
    assert waiting.id != stale.id


async def test_recover_stale_requeues_a_send_that_was_cut_off(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    await _queue_reply(store)
    record = await store.claim_outbox()
    assert record is not None
    sql.execute("UPDATE outbox SET claimed_at = now() - interval '2 hours'")

    assert await store.recover_stale(900) == 1

    assert one(sql, "SELECT status FROM outbox")["status"] == "pending"
    assert await store.claim_outbox() is not None


async def test_recover_stale_leaves_a_recent_send_alone(
    store: ConversationStore, sql: psycopg.Connection
) -> None:
    await _queue_reply(store)
    assert await store.claim_outbox() is not None

    await store.recover_stale(900)

    assert one(sql, "SELECT status FROM outbox")["status"] == "sending"
