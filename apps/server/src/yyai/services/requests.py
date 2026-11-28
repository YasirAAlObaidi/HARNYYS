"""Quote requests and handovers: the business rules around what the agent records for staff.

The tools in workflows/agent/request_tools.py call this. Identity (which chat) always comes from the caller's
RunContext; nothing here takes a customer or phone number from the model.
"""

from __future__ import annotations

from decimal import Decimal

from yyai.core.errors import YyaiError
from yyai.core.types import HandoverReason, HandoverRecord, HandoverSource, QuoteRequestRecord
from yyai.handlers.persistence.requests import RequestStore

MAX_QUANTITY = Decimal(10000)
MAX_OPEN_QUOTE_REQUESTS = 10  # per chat: more than this is not a real customer, so stop recording
MAX_AREA_CHARS = 100
MAX_NOTE_CHARS = 200


class RequestRejected(YyaiError, ValueError):
    """The request breaks a rule. The message is written for the model, so it can correct itself."""


class RequestService:
    def __init__(self, store: RequestStore) -> None:
        self._store = store

    async def request_quote(
        self,
        *,
        conversation_id: int,
        turn_id: int | None,
        code: str,
        product_name: str,
        quantity: Decimal,
        unit: str | None = None,
        area: str | None = None,
        note: str | None = None,
    ) -> QuoteRequestRecord:
        if not Decimal(0) < quantity <= MAX_QUANTITY:
            raise RequestRejected(f"quantity must be more than 0 and at most {MAX_QUANTITY}")
        area, note = _clean(area, MAX_AREA_CHARS), _clean(note, MAX_NOTE_CHARS)
        if await self._store.open_quote_requests(conversation_id) >= MAX_OPEN_QUOTE_REQUESTS:
            raise RequestRejected(
                "this chat already has the most open quote requests allowed; call handover_to_staff instead"
            )
        return await self._store.save_quote_request(
            conversation_id=conversation_id,
            turn_id=turn_id,
            code=code,
            product_name=product_name,
            quantity=quantity,
            unit=_clean(unit, 20),
            area=area,
            note=note,
        )

    async def hand_over(
        self,
        *,
        conversation_id: int,
        turn_id: int | None,
        reason: HandoverReason,
        summary: str | None = None,
        source: HandoverSource = "tool",
    ) -> HandoverRecord:
        return await self._store.open_handover(
            conversation_id=conversation_id,
            turn_id=turn_id,
            reason=reason,
            summary=_clean(summary, MAX_NOTE_CHARS),
            source=source,
        )


def _clean(value: str | None, limit: int) -> str | None:
    """Trim, collapse spaces, cut to the column's limit. Empty becomes None."""
    if value is None:
        return None
    value = " ".join(value.split())
    return value[:limit] or None
