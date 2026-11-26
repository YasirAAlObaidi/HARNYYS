"""Conversations, messages, turns, outbox and the audit log.

The `turns` and `outbox` tables are the work queue. The worker claims rows with
FOR UPDATE SKIP LOCKED. Partial unique indexes guarantee at most one waiting and
one running turn per conversation, which acts as the per-conversation lock.
See docs/decisions/0007.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from yyai.core.types import (
    Author,
    ConversationSummary,
    Direction,
    InboundMessage,
    OutboxRecord,
    StoredMessage,
    TranscriptMessage,
    TurnRecord,
)
from yyai.handlers.persistence.db import Database


class ConversationStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def ping(self) -> bool:
        return await self._db.ping()

    # --- inbound ---------------------------------------------------------

    async def record_inbound(self, message: InboundMessage) -> tuple[int, bool]:
        """Save one inbound message and queue a turn, in one transaction.

        Returns (conversation_id, is_new). A message we have seen before
        (same provider message ID) is ignored and queues nothing.
        """
        async with self._db.engine.begin() as conn:
            conversation_id = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO conversations
                          (channel, external_user_id, customer_name, last_inbound_at, internal)
                        VALUES (:channel, :user, :name, :at, :internal)
                        ON CONFLICT (channel, external_user_id) DO UPDATE
                          SET customer_name = COALESCE(EXCLUDED.customer_name, conversations.customer_name),
                              last_inbound_at = GREATEST(conversations.last_inbound_at, EXCLUDED.last_inbound_at),
                              -- once internal, always internal: a staff chat never turns into a customer chat
                              internal = conversations.internal OR EXCLUDED.internal
                        RETURNING id
                        """
                    ),
                    {
                        "channel": message.channel,
                        "user": message.sender_id,
                        "name": message.sender_name,
                        "at": message.received_at,
                        "internal": message.internal,
                    },
                )
            ).scalar_one()
            inserted = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO messages (conversation_id, direction, source_id, text, media, created_at)
                        VALUES (:cid, 'in', :source_id, :text, CAST(:media AS jsonb), :at)
                        ON CONFLICT (conversation_id, source_id) WHERE source_id IS NOT NULL DO NOTHING
                        RETURNING id
                        """
                    ),
                    {
                        "cid": conversation_id,
                        "source_id": message.source_id,
                        "text": message.text,
                        "media": json.dumps([m.model_dump() for m in message.media]),
                        "at": message.received_at,
                    },
                )
            ).scalar_one_or_none()
            if inserted is None:
                return conversation_id, False
            await conn.execute(
                text(
                    """
                    INSERT INTO turns (conversation_id, state) VALUES (:cid, 'received')
                    ON CONFLICT (conversation_id) WHERE state = 'received' DO NOTHING
                    """
                ),
                {"cid": conversation_id},
            )
            return conversation_id, True

    # --- turns -----------------------------------------------------------

    async def claim_turn(self) -> TurnRecord | None:
        try:
            async with self._db.engine.begin() as conn:
                row = (
                    await conn.execute(
                        text(
                            """
                            UPDATE turns SET state = 'running', started_at = now(), attempts = attempts + 1
                            WHERE id = (
                              SELECT t.id FROM turns t
                              WHERE t.state = 'received'
                                AND NOT EXISTS (
                                  SELECT 1 FROM turns r
                                  WHERE r.conversation_id = t.conversation_id AND r.state = 'running')
                              ORDER BY t.id
                              FOR UPDATE SKIP LOCKED
                              LIMIT 1)
                            RETURNING id, conversation_id, attempts
                            """
                        )
                    )
                ).first()
                if row is None:
                    return None
                conv = (
                    await conn.execute(
                        text(
                            "SELECT channel, external_user_id, customer_name, internal FROM conversations"
                            " WHERE id = :id"
                        ),
                        {"id": row.conversation_id},
                    )
                ).one()
        except IntegrityError:
            # Another worker started a turn for this conversation at the same moment.
            return None
        return TurnRecord(
            id=row.id,
            conversation_id=row.conversation_id,
            channel=conv.channel,
            external_user_id=conv.external_user_id,
            customer_name=conv.customer_name,
            attempts=row.attempts,
            internal=conv.internal,
        )

    async def finish_turn(self, turn_id: int, conversation_id: int, reply: str | None, *, auto_send: bool, steps: int) -> None:
        """Save the reply, put it in the outbox, and move the turn on. One transaction."""
        async with self._db.engine.begin() as conn:
            if not reply:
                await conn.execute(
                    text("UPDATE turns SET state = 'done', steps = :steps, finished_at = now() WHERE id = :id"),
                    {"id": turn_id, "steps": steps},
                )
                return
            message_id = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO messages (conversation_id, direction, text, turn_id)
                        VALUES (:cid, 'out', :text, :tid) RETURNING id
                        """
                    ),
                    {"cid": conversation_id, "text": reply, "tid": turn_id},
                )
            ).scalar_one()
            await conn.execute(
                text(
                    """
                    INSERT INTO outbox (conversation_id, turn_id, message_id, text, status)
                    VALUES (:cid, :tid, :mid, :text, :status)
                    """
                ),
                {
                    "cid": conversation_id,
                    "tid": turn_id,
                    "mid": message_id,
                    "text": reply,
                    "status": "pending" if auto_send else "awaiting_approval",
                },
            )
            await conn.execute(
                text("UPDATE turns SET state = 'sending', steps = :steps, finished_at = now() WHERE id = :id"),
                {"id": turn_id, "steps": steps},
            )

    async def fail_turn(self, turn_id: int, error: str) -> None:
        async with self._db.engine.begin() as conn:
            await conn.execute(
                text("UPDATE turns SET state = 'failed', error = :error, finished_at = now() WHERE id = :id"),
                {"id": turn_id, "error": error[:2000]},
            )

    async def recover_stale(self, older_than_s: float, max_attempts: int = 3) -> int:
        """Put turns and sends that were cut off by a crash back in the queue. Returns how many rows it touched."""
        async with self._db.engine.begin() as conn:
            failed = await conn.execute(
                text(
                    """
                    UPDATE turns SET state = 'failed', error = 'worker stopped mid-turn too often', finished_at = now()
                    WHERE state = 'running' AND started_at < now() - make_interval(secs => :age)
                      AND (attempts >= :max OR EXISTS (
                        SELECT 1 FROM turns w WHERE w.conversation_id = turns.conversation_id AND w.state = 'received'))
                    """
                ),
                {"age": older_than_s, "max": max_attempts},
            )
            retried = await conn.execute(
                text(
                    """
                    UPDATE turns SET state = 'received'
                    WHERE state = 'running' AND started_at < now() - make_interval(secs => :age)
                    """
                ),
                {"age": older_than_s},
            )
            # At-least-once: a send cut off mid-way may be repeated once.
            resent = await conn.execute(
                text(
                    """
                    UPDATE outbox SET status = 'pending'
                    WHERE status = 'sending' AND claimed_at < now() - make_interval(secs => :age)
                    """
                ),
                {"age": older_than_s},
            )
        return (failed.rowcount or 0) + (retried.rowcount or 0) + (resent.rowcount or 0)

    async def history(self, conversation_id: int, limit: int) -> list[StoredMessage]:
        async with self._db.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT id, direction, text, created_at FROM (
                          SELECT id, direction, text, created_at FROM messages
                          WHERE conversation_id = :cid ORDER BY id DESC LIMIT :limit) recent
                        ORDER BY id
                        """
                    ),
                    {"cid": conversation_id, "limit": limit},
                )
            ).all()
        return [StoredMessage(id=r.id, direction=Direction(r.direction), text=r.text, created_at=r.created_at) for r in rows]

    async def audit(self, turn_id: int | None, kind: str, name: str | None, data: dict[str, Any]) -> None:
        async with self._db.engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO audit_log (turn_id, kind, name, data) VALUES (:tid, :kind, :name, CAST(:data AS jsonb))"),
                {"tid": turn_id, "kind": kind, "name": name, "data": json.dumps(data, ensure_ascii=False, default=str)},
            )

    # --- outbox ----------------------------------------------------------

    async def claim_outbox(self) -> OutboxRecord | None:
        async with self._db.engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        UPDATE outbox SET status = 'sending', attempts = attempts + 1, claimed_at = now()
                        WHERE id = (
                          SELECT id FROM outbox
                          WHERE status = 'pending' AND next_attempt_at <= now()
                          ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
                        RETURNING id, conversation_id, turn_id, text, attempts
                        """
                    )
                )
            ).first()
            if row is None:
                return None
            conv = (
                await conn.execute(
                    text("SELECT channel, external_user_id, last_inbound_at FROM conversations WHERE id = :id"),
                    {"id": row.conversation_id},
                )
            ).one()
        return OutboxRecord(
            id=row.id,
            conversation_id=row.conversation_id,
            turn_id=row.turn_id,
            channel=conv.channel,
            to=conv.external_user_id,
            text=row.text,
            attempts=row.attempts,
            last_inbound_at=conv.last_inbound_at,
        )

    async def mark_sent(self, outbox_id: int, turn_id: int | None, provider_message_id: str) -> None:
        async with self._db.engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE outbox SET status = 'sent', provider_message_id = :pid, sent_at = now(), last_error = NULL
                    WHERE id = :id
                    """
                ),
                {"id": outbox_id, "pid": provider_message_id},
            )
            if turn_id is not None:
                await conn.execute(text("UPDATE turns SET state = 'sent' WHERE id = :id"), {"id": turn_id})

    async def mark_send_failed(self, outbox_id: int, turn_id: int | None, error: str, retry_at: datetime | None) -> None:
        async with self._db.engine.begin() as conn:
            if retry_at is None:
                await conn.execute(
                    text("UPDATE outbox SET status = 'failed', last_error = :error WHERE id = :id"),
                    {"id": outbox_id, "error": error[:2000]},
                )
                if turn_id is not None:
                    await conn.execute(
                        text("UPDATE turns SET state = 'failed', error = :error WHERE id = :id"),
                        {"id": turn_id, "error": f"send failed: {error[:1900]}"},
                    )
            else:
                await conn.execute(
                    text("UPDATE outbox SET status = 'pending', last_error = :error, next_attempt_at = :at WHERE id = :id"),
                    {"id": outbox_id, "error": error[:2000], "at": retry_at},
                )

    async def approve_outbox(self, outbox_id: int) -> bool:
        async with self._db.engine.begin() as conn:
            result = await conn.execute(
                text("UPDATE outbox SET status = 'pending' WHERE id = :id AND status = 'awaiting_approval'"),
                {"id": outbox_id},
            )
        return (result.rowcount or 0) > 0

    # --- read-only views for the API -------------------------------------

    async def list_conversations(
        self, limit: int, query: str | None = None, digits: str | None = None
    ) -> list[ConversationSummary]:
        """Customer chats, newest activity first. Internal (staff) chats are never listed.

        `query` matches the name, the number or any message text. `digits` (the query with only its digits
        kept, when it looks like a phone number) also matches the number with spaces and + ignored.
        """
        search = ""
        params: dict[str, Any] = {"limit": limit}
        if query:
            search = _SEARCH_DIGITS if digits else _SEARCH
            params.update(pattern=_like(query), digits=_like(digits or ""))
        async with self._db.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        f"""
                        SELECT c.id, c.channel, c.external_user_id, c.customer_name, c.last_inbound_at,
                               c.created_at, c.internal,
                               lm.created_at AS last_message_at, left(lm.text, 200) AS last_message_text,
                               lm.direction AS last_direction, lm.turn_id AS last_turn_id,
                               (SELECT count(*) FROM messages n WHERE n.conversation_id = c.id) AS message_count
                        FROM conversations c
                        LEFT JOIN LATERAL (
                          SELECT created_at, text, direction, turn_id FROM messages
                          WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) lm ON true
                        WHERE NOT c.internal {search}
                        ORDER BY COALESCE(lm.created_at, c.last_inbound_at, c.created_at) DESC, c.id DESC
                        LIMIT :limit
                        """
                    ),
                    params,
                )
            ).all()
        return [_summary(row._asdict()) for row in rows]

    async def get_conversation(self, conversation_id: int) -> ConversationSummary | None:
        async with self._db.engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT id, channel, external_user_id, customer_name, last_inbound_at, created_at, internal
                        FROM conversations WHERE id = :id
                        """
                    ),
                    {"id": conversation_id},
                )
            ).first()
        return _summary(row._asdict()) if row else None

    async def find_conversation(self, channel: str, external_user_id: str) -> int | None:
        async with self._db.engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT id FROM conversations WHERE channel = :channel AND external_user_id = :user"),
                    {"channel": channel, "user": external_user_id},
                )
            ).scalar_one_or_none()

    async def transcript(
        self, conversation_id: int, limit: int, after_id: int | None = None
    ) -> list[TranscriptMessage]:
        """The newest `limit` messages (after `after_id`, if given), oldest first, as staff see them."""
        async with self._db.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT * FROM (
                          SELECT m.id, m.direction, m.text, m.media, m.turn_id, m.created_at, o.status AS delivery
                          FROM messages m
                          LEFT JOIN LATERAL (
                            SELECT status FROM outbox WHERE message_id = m.id ORDER BY id DESC LIMIT 1) o ON true
                          WHERE m.conversation_id = :cid AND m.id > :after
                          ORDER BY m.id DESC LIMIT :limit) recent
                        ORDER BY id
                        """
                    ),
                    {"cid": conversation_id, "limit": limit, "after": after_id or 0},
                )
            ).all()
        return [
            TranscriptMessage(
                id=r.id,
                direction=Direction(r.direction),
                author=_author(r.direction, r.turn_id),
                text=r.text,
                media=[str(m.get("kind", "other")) for m in (r.media or []) if isinstance(m, dict)],
                created_at=r.created_at,
                delivery=r.delivery,
            )
            for r in rows
        ]

    async def has_pending_turn(self, conversation_id: int) -> bool:
        """True while a turn is waiting or running, so the reply is still to come."""
        async with self._db.engine.connect() as conn:
            return bool(
                (
                    await conn.execute(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM turns WHERE conversation_id = :cid"
                            " AND state IN ('received', 'running'))"
                        ),
                        {"cid": conversation_id},
                    )
                ).scalar_one()
            )


# A message from the customer is "in". A reply written by an agent turn has a turn_id. Any other "out" message
# was written by a member of staff (staff replies are not built yet, but the transcript already tells them apart).
def _author(direction: str, turn_id: int | None) -> Author:
    if direction == Direction.INBOUND:
        return "customer"
    return "ai" if turn_id is not None else "staff"


def _summary(row: dict[str, Any]) -> ConversationSummary:
    direction = row.pop("last_direction", None)
    turn_id = row.pop("last_turn_id", None)
    if direction is not None:
        row["last_message_author"] = _author(direction, turn_id)
    return ConversationSummary.model_validate(row)


_SEARCH = """
  AND (c.customer_name ILIKE :pattern OR c.external_user_id ILIKE :pattern
       OR EXISTS (SELECT 1 FROM messages s WHERE s.conversation_id = c.id AND s.text ILIKE :pattern))
"""
_SEARCH_DIGITS = """
  AND (c.customer_name ILIKE :pattern OR c.external_user_id ILIKE :pattern
       OR regexp_replace(c.external_user_id, '[^0-9]', '', 'g') LIKE :digits
       OR EXISTS (SELECT 1 FROM messages s WHERE s.conversation_id = c.id AND s.text ILIKE :pattern))
"""


def _like(value: str) -> str:
    """A LIKE pattern that matches `value` anywhere, with the user's own % and _ taken literally."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
