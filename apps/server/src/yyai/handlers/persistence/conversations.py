"""Conversations, messages, turns, outbox and the audit log.

The `turns` and `outbox` tables are the work queue. The worker claims rows with
FOR UPDATE SKIP LOCKED. Partial unique indexes guarantee at most one waiting and
one running turn per conversation, which acts as the per-conversation lock.
See docs/decisions/0007.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from yyai.core.types import (
    ConversationSummary,
    Direction,
    InboundMessage,
    OutboundImage,
    OutboxRecord,
    StoredMessage,
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
                        INSERT INTO conversations (channel, external_user_id, customer_name, last_inbound_at)
                        VALUES (:channel, :user, :name, :at)
                        ON CONFLICT (channel, external_user_id) DO UPDATE
                          SET customer_name = COALESCE(EXCLUDED.customer_name, conversations.customer_name),
                              last_inbound_at = GREATEST(conversations.last_inbound_at, EXCLUDED.last_inbound_at)
                        RETURNING id
                        """
                    ),
                    {
                        "channel": message.channel,
                        "user": message.sender_id,
                        "name": message.sender_name,
                        "at": message.received_at,
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
                        text("SELECT channel, external_user_id, customer_name FROM conversations WHERE id = :id"),
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
        )

    async def finish_turn(
        self,
        turn_id: int,
        conversation_id: int,
        reply: str | None,
        *,
        auto_send: bool,
        steps: int,
        images: Sequence[OutboundImage] = (),
    ) -> None:
        """Save the reply, put it and its images in the outbox (text first), and move the turn on. One transaction."""
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
            status = "pending" if auto_send else "awaiting_approval"
            await conn.execute(
                text(
                    """
                    INSERT INTO outbox (conversation_id, turn_id, message_id, text, status)
                    VALUES (:cid, :tid, :mid, :text, :status)
                    """
                ),
                {"cid": conversation_id, "tid": turn_id, "mid": message_id, "text": reply, "status": status},
            )
            for image in images:  # inserted after the text, so their ids (the send order) are higher
                await conn.execute(
                    text(
                        """
                        INSERT INTO outbox (conversation_id, turn_id, kind, image_url, text, status)
                        VALUES (:cid, :tid, 'image', :url, :caption, :status)
                        """
                    ),
                    {"cid": conversation_id, "tid": turn_id, "url": image.url, "caption": image.caption, "status": status},
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
                          SELECT o.id FROM outbox o
                          WHERE o.status = 'pending' AND o.next_attempt_at <= now()
                            -- A turn's messages go out in order: wait while an earlier one is still unsent.
                            AND NOT EXISTS (
                              SELECT 1 FROM outbox e
                              WHERE e.turn_id = o.turn_id AND e.id < o.id
                                AND e.status IN ('awaiting_approval', 'pending', 'sending'))
                          ORDER BY o.id FOR UPDATE SKIP LOCKED LIMIT 1)
                        RETURNING id, conversation_id, turn_id, text, kind, image_url, attempts
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
            kind=row.kind,
            image_url=row.image_url,
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
                # The turn is 'sent' only when every message of the turn has gone out.
                await conn.execute(
                    text(
                        """
                        UPDATE turns SET state = 'sent' WHERE id = :id AND NOT EXISTS (
                          SELECT 1 FROM outbox WHERE turn_id = :id AND status IN ('awaiting_approval', 'pending', 'sending'))
                        """
                    ),
                    {"id": turn_id},
                )

    async def mark_send_failed(self, outbox_id: int, turn_id: int | None, error: str, retry_at: datetime | None) -> None:
        async with self._db.engine.begin() as conn:
            if retry_at is None:
                kind = (
                    await conn.execute(
                        text("UPDATE outbox SET status = 'failed', last_error = :error WHERE id = :id RETURNING kind"),
                        {"id": outbox_id, "error": error[:2000]},
                    )
                ).scalar_one_or_none()
                if turn_id is not None and kind == "image":
                    # The reply text was delivered, so a lost picture does not fail the turn.
                    await conn.execute(
                        text(
                            """
                            UPDATE turns SET state = 'sent' WHERE id = :id AND state = 'sending' AND NOT EXISTS (
                              SELECT 1 FROM outbox WHERE turn_id = :id AND status IN ('awaiting_approval', 'pending', 'sending'))
                            """
                        ),
                        {"id": turn_id},
                    )
                elif turn_id is not None:
                    # The text did not go out, so its pictures must not go out alone.
                    await conn.execute(
                        text(
                            """
                            UPDATE outbox SET status = 'failed', last_error = 'the reply text of this turn was not sent'
                            WHERE turn_id = :id AND id > :oid AND status IN ('awaiting_approval', 'pending')
                            """
                        ),
                        {"id": turn_id, "oid": outbox_id},
                    )
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

    async def list_conversations(self, limit: int) -> list[ConversationSummary]:
        async with self._db.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT id, channel, external_user_id, customer_name, last_inbound_at, created_at
                        FROM conversations ORDER BY COALESCE(last_inbound_at, created_at) DESC LIMIT :limit
                        """
                    ),
                    {"limit": limit},
                )
            ).all()
        return [ConversationSummary.model_validate(r._asdict()) for r in rows]
