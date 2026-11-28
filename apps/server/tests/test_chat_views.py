"""The Chats page's data: the chat list (never internal chats), search, and transcripts with authors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from yyai.core.errors import NotFound
from yyai.core.text import phone_digits, western_digits
from yyai.core.types import STAFF_CHANNEL, InboundMessage, MediaRef, RunContext
from yyai.handlers.persistence.conversations import ConversationStore
from yyai.handlers.persistence.db import Database
from yyai.services.conversation import ConversationService
from yyai.workflows.queries import ConversationQueries

T0 = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)


def inbound(
    source_id: str,
    sender: str,
    text: str,
    *,
    at: datetime,
    name: str | None = None,
    internal: bool = False,
    channel: str = "whatsapp",
    media: list[MediaRef] | None = None,
) -> InboundMessage:
    return InboundMessage(
        channel=channel,
        source_id=source_id,
        sender_id=sender,
        sender_name=name,
        text=text,
        received_at=at,
        internal=internal,
        media=media or [],
    )


@pytest.fixture
def store(db: Database) -> ConversationStore:
    return ConversationStore(db)


@pytest.fixture
def queries(store: ConversationStore) -> ConversationQueries:
    return ConversationQueries(ConversationService(store))


async def reply(store: ConversationStore, conversation_id: int, text: str) -> None:
    turn = await store.claim_turn()
    assert turn is not None and turn.conversation_id == conversation_id
    await store.finish_turn(turn.id, conversation_id, text, auto_send=True, steps=1)


@pytest.mark.db
async def test_the_chat_list_never_shows_internal_chats(store: ConversationStore, queries: ConversationQueries) -> None:
    await store.record_inbound(inbound("w1", "971501111111", "hello", at=T0, name="Alice"))
    staff_id, _ = await store.record_inbound(
        inbound("s1", "staff-1", "price of colombia?", at=T0, internal=True, channel=STAFF_CHANNEL)
    )

    listed = await queries.list_conversations(50)

    assert [c.customer_name for c in listed] == ["Alice"]
    with pytest.raises(NotFound):
        await queries.messages(staff_id, 100)
    with pytest.raises(NotFound):
        await queries.conversation(staff_id)
    with pytest.raises(NotFound):
        await queries.messages(999, 100)


@pytest.mark.db
async def test_an_internal_chat_stays_internal(store: ConversationStore, sql: psycopg.Connection) -> None:
    await store.record_inbound(inbound("s1", "staff-1", "hi", at=T0, internal=True, channel=STAFF_CHANNEL))
    await store.record_inbound(inbound("s2", "staff-1", "hi again", at=T0, internal=False, channel=STAFF_CHANNEL))

    assert sql.execute("SELECT internal FROM conversations").fetchone()["internal"] is True


@pytest.mark.db
async def test_the_list_shows_the_newest_message_and_is_sorted_by_activity(
    store: ConversationStore, queries: ConversationQueries
) -> None:
    alice, _ = await store.record_inbound(inbound("a1", "971501111111", "first", at=T0, name="Alice"))
    await store.record_inbound(inbound("b1", "971502222222", "مرحبا", at=T0 + timedelta(minutes=5), name="Bader"))
    await reply(store, alice, "Welcome to Kahraman")  # Alice's chat now has the newest message

    listed = await queries.list_conversations(50)

    assert [c.customer_name for c in listed] == ["Alice", "Bader"]
    assert (listed[0].last_message_text, listed[0].last_message_author, listed[0].message_count) == (
        "Welcome to Kahraman",
        "ai",
        2,
    )
    assert (listed[1].last_message_text, listed[1].last_message_author) == ("مرحبا", "customer")


@pytest.mark.db
async def test_search_by_name_number_eastern_digits_or_words(
    store: ConversationStore, queries: ConversationQueries
) -> None:
    await store.record_inbound(inbound("a1", "971501234567", "do you have chemex?", at=T0, name="Alice"))
    await store.record_inbound(inbound("b1", "971559876543", "كم سعر الكولومبي", at=T0, name="بدر"))

    async def names(q: str) -> list[str | None]:
        return [c.customer_name for c in await queries.list_conversations(50, q)]

    assert await names("alice") == ["Alice"]
    assert await names("بدر") == ["بدر"]
    assert await names("+971 50 123") == ["Alice"]
    assert await names("٩٨٧٦") == ["بدر"]  # Eastern Arabic digits find the number
    assert await names("CHEMEX") == ["Alice"]
    assert await names("الكولومبي") == ["بدر"]
    assert await names("100%") == []  # the user's % is a literal character, not a wildcard
    assert sorted(await names("  ")) == ["Alice", "بدر"]


@pytest.mark.db
async def test_the_transcript_tells_customer_ai_and_staff_apart(
    store: ConversationStore, queries: ConversationQueries, sql: psycopg.Connection
) -> None:
    cid, _ = await store.record_inbound(
        inbound(
            "a1",
            "971501111111",
            "[audio]",
            at=T0,
            media=[MediaRef(kind="audio", provider_id="m-1", mime_type="audio/ogg")],
        )
    )
    await reply(store, cid, "Sorry, I cannot listen to voice notes yet.")
    sql.execute("INSERT INTO messages (conversation_id, direction, text) VALUES (%s, 'out', 'Staff here')", (cid,))

    transcript = await queries.messages(cid, 100)

    assert [(m.author, m.text, m.media, m.delivery) for m in transcript] == [
        ("customer", "[audio]", ["audio"], None),
        ("ai", "Sorry, I cannot listen to voice notes yet.", [], "pending"),
        ("staff", "Staff here", [], None),
    ]
    newer = await queries.messages(cid, 100, after_id=transcript[0].id)
    assert [m.author for m in newer] == ["ai", "staff"]


def test_digit_helpers() -> None:
    assert western_digits("٠٥٠ ۱۲۳") == "050 123"
    assert phone_digits("+971 (50) 123-45") == "9715012345"
    assert phone_digits("٠٥٠١٢٣") == "050123"
    assert phone_digits("12") is None
    assert phone_digits("colombia 1kg") is None


def test_a_staff_turn_is_internal_even_if_the_caller_forgets() -> None:
    common = {
        "turn_id": 1,
        "conversation_id": 1,
        "customer_id": "staff-1",
        "customer_name": "Sara",
        "client_name": "Kahraman",
        "currency": "AED",
        "auto_send": True,
    }
    assert RunContext(channel=STAFF_CHANNEL, **common).internal is True
    assert RunContext(channel="whatsapp", **common).internal is False
    assert RunContext(channel="whatsapp", internal=True, **common).internal is True
