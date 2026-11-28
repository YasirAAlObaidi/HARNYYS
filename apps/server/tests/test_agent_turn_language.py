"""The language hint names the script of the customer's latest message."""

from datetime import UTC, datetime

from yyai.core.types import Direction, StoredMessage
from yyai.workflows.agent.turn import language_hint


def msg(direction: Direction, text: str) -> StoredMessage:
    return StoredMessage(id=1, direction=direction, text=text, created_at=datetime.now(UTC))


def test_english_message_gets_an_english_hint_even_after_arabic_replies() -> None:
    history = [msg(Direction.INBOUND, "ازيك"), msg(Direction.OUTBOUND, "أهلاً"), msg(Direction.INBOUND, "I want a grinder")]
    assert "Latin letters" in language_hint(history)


def test_arabic_message_gets_an_arabic_hint() -> None:
    assert "Arabic" in language_hint([msg(Direction.INBOUND, "كم سعر المطحنة؟")])


def test_emoji_or_mixed_messages_get_no_hint() -> None:
    assert language_hint([msg(Direction.INBOUND, "👍")]) == ""
    assert language_hint([msg(Direction.INBOUND, "عندكم Ethiopia Gesha Village")]) == ""
