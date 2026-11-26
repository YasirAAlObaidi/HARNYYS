"""Quote requests and handovers in our database (migration 0004).

The partial unique indexes keep at most one open quote request per chat and product, and one open handover
per chat, so a repeated call updates the open row. `created` in the result says which happened.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import text

from yyai.core.types import HandoverReason, HandoverRecord, HandoverSource, QuoteRequestRecord
from yyai.handlers.persistence.db import Database


class RequestStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_quote_request(
        self,
        *,
        conversation_id: int,
        turn_id: int | None,
        code: str,
        product_name: str,
        quantity: Decimal,
        unit: str | None,
        area: str | None,
        note: str | None,
    ) -> QuoteRequestRecord:
        async with self._db.engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO quote_requests
                          (conversation_id, turn_id, code, product_name, quantity, unit, area, note)
                        VALUES (:conversation_id, :turn_id, :code, :product_name, :quantity, :unit, :area, :note)
                        ON CONFLICT (conversation_id, code) WHERE status = 'open' DO UPDATE SET
                          turn_id = EXCLUDED.turn_id, product_name = EXCLUDED.product_name,
                          quantity = EXCLUDED.quantity, unit = EXCLUDED.unit,
                          area = COALESCE(EXCLUDED.area, quote_requests.area),
                          note = COALESCE(EXCLUDED.note, quote_requests.note),
                          updated_at = now()
                        RETURNING id, conversation_id, code, product_name, quantity, unit, area, note, status,
                                  (xmax = 0) AS created
                        """
                    ),
                    {
                        "conversation_id": conversation_id,
                        "turn_id": turn_id,
                        "code": code,
                        "product_name": product_name,
                        "quantity": quantity,
                        "unit": unit,
                        "area": area,
                        "note": note,
                    },
                )
            ).one()
        return QuoteRequestRecord.model_validate(row._asdict())

    async def open_quote_requests(self, conversation_id: int) -> int:
        async with self._db.engine.connect() as conn:
            return int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM quote_requests WHERE conversation_id = :id AND status = 'open'"
                        ),
                        {"id": conversation_id},
                    )
                ).scalar_one()
            )

    async def open_handover(
        self,
        *,
        conversation_id: int,
        turn_id: int | None,
        reason: HandoverReason,
        summary: str | None,
        source: HandoverSource,
    ) -> HandoverRecord:
        """Open a handover, or return the chat's open one (its summary is filled in if it had none)."""
        async with self._db.engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO handovers (conversation_id, turn_id, reason, summary, source)
                        VALUES (:conversation_id, :turn_id, :reason, :summary, :source)
                        ON CONFLICT (conversation_id) WHERE status = 'open' DO UPDATE SET
                          summary = COALESCE(handovers.summary, EXCLUDED.summary), updated_at = now()
                        RETURNING id, conversation_id, reason, summary, source, (xmax = 0) AS created
                        """
                    ),
                    {
                        "conversation_id": conversation_id,
                        "turn_id": turn_id,
                        "reason": reason,
                        "summary": summary,
                        "source": source,
                    },
                )
            ).one()
        return HandoverRecord.model_validate(row._asdict())
