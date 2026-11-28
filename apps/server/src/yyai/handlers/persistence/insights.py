"""Raw rows for the Insights page, and the hourly snapshots computed from them.

Every query here joins `conversations` and keeps only customer chats (`NOT internal`), so staff chats from the
Assistant page can never reach the numbers.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text

from yyai.core.types import ContactRow, CustomerMessageRow, InsightSnapshot, ToolCallRow
from yyai.handlers.persistence.db import Database

PREVIEW_CHARS = 500  # language and keyword checks need only the start of a message


class InsightStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def customer_messages(self, since: datetime) -> list[CustomerMessageRow]:
        """Messages customers sent since `since`."""
        async with self._db.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT m.conversation_id, m.created_at, left(m.text, :chars) AS text,
                               COALESCE((SELECT array_agg(e->>'kind') FROM jsonb_array_elements(m.media) e),
                                        '{}') AS media
                        FROM messages m JOIN conversations c ON c.id = m.conversation_id
                        WHERE m.direction = 'in' AND NOT c.internal AND m.created_at >= :since
                        """
                    ),
                    {"since": since, "chars": PREVIEW_CHARS},
                )
            ).all()
        return [
            CustomerMessageRow(r.conversation_id, r.created_at, r.text or "", tuple(k for k in r.media if k))
            for r in rows
        ]

    async def contacts_active_since(self, since: datetime) -> list[ContactRow]:
        """Every customer who wrote since `since`, with the time they first wrote (which may be long before)."""
        async with self._db.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT m.conversation_id, min(m.created_at) AS first_at
                        FROM messages m JOIN conversations c ON c.id = m.conversation_id
                        WHERE m.direction = 'in' AND NOT c.internal
                        GROUP BY m.conversation_id
                        HAVING max(m.created_at) >= :since
                        """
                    ),
                    {"since": since},
                )
            ).all()
        return [ContactRow(r.conversation_id, r.first_at) for r in rows]

    async def tool_calls(self, since: datetime) -> list[ToolCallRow]:
        """Tool calls the agent made in customer chats since `since`, from the audit log."""
        async with self._db.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT t.conversation_id, a.name, a.data->'args' AS args, a.data->>'result' AS result,
                               a.created_at
                        FROM audit_log a
                        JOIN turns t ON t.id = a.turn_id
                        JOIN conversations c ON c.id = t.conversation_id
                        WHERE a.kind = 'tool_call' AND NOT c.internal AND a.created_at >= :since
                        """
                    ),
                    {"since": since},
                )
            ).all()
        return [
            ToolCallRow(
                r.conversation_id,
                r.name or "",
                r.args if isinstance(r.args, dict) else {},
                r.result or "",
                r.created_at,
            )
            for r in rows
        ]

    # --- snapshots -----------------------------------------------------------

    async def save_snapshot(self, computed_at: datetime, data: dict[str, Any]) -> InsightSnapshot:
        async with self._db.engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO insight_snapshots (computed_at, data) VALUES (:at, CAST(:data AS jsonb))
                        RETURNING id, computed_at, data
                        """
                    ),
                    {"at": computed_at, "data": json.dumps(data, ensure_ascii=False)},
                )
            ).one()
        return InsightSnapshot(id=row.id, computed_at=row.computed_at, data=row.data)

    async def latest_snapshot(self) -> InsightSnapshot | None:
        async with self._db.engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT id, computed_at, data FROM insight_snapshots ORDER BY computed_at DESC, id DESC LIMIT 1")
                )
            ).first()
        return InsightSnapshot(id=row.id, computed_at=row.computed_at, data=row.data) if row else None

    async def prune_snapshots(self, before: datetime) -> int:
        """Delete snapshots older than `before`, always keeping the newest one."""
        async with self._db.engine.begin() as conn:
            result = await conn.execute(
                text(
                    """
                    DELETE FROM insight_snapshots WHERE computed_at < :before
                      AND id <> (SELECT id FROM insight_snapshots ORDER BY computed_at DESC, id DESC LIMIT 1)
                    """
                ),
                {"before": before},
            )
        return result.rowcount or 0
