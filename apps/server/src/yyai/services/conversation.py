"""Conversations, turns, the outbox and the audit log, as business operations.

A thin wrapper over the conversation store. Workflows call this, never the
store, so the layers stay clean and storage can change without touching them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from yyai.core.types import (
    ConversationSummary,
    InboundMessage,
    OutboxRecord,
    StoredMessage,
    TurnRecord,
)
from yyai.handlers.persistence.conversations import ConversationStore


class ConversationService:
    def __init__(self, store: ConversationStore) -> None:
        self._store = store

    async def ping(self) -> bool:
        return await self._store.ping()

    # --- inbound ---------------------------------------------------------

    async def record_inbound(self, messages: list[InboundMessage]) -> dict[str, int]:
        """Save each message and queue a turn for it. Duplicates are counted as received but not new."""
        new = 0
        for message in messages:
            _, is_new = await self._store.record_inbound(message)
            if is_new:
                new += 1
        return {"received": len(messages), "new": new}

    # --- turns -----------------------------------------------------------

    async def claim_turn(self) -> TurnRecord | None:
        return await self._store.claim_turn()

    async def history(self, conversation_id: int, limit: int) -> list[StoredMessage]:
        return await self._store.history(conversation_id, limit)

    async def finish_turn(
        self, turn_id: int, conversation_id: int, reply: str | None, *, auto_send: bool, steps: int
    ) -> None:
        await self._store.finish_turn(turn_id, conversation_id, reply, auto_send=auto_send, steps=steps)

    async def fail_turn(self, turn_id: int, error: str) -> None:
        await self._store.fail_turn(turn_id, error)

    async def audit(self, turn_id: int | None, kind: str, name: str | None, data: dict[str, Any]) -> None:
        await self._store.audit(turn_id, kind, name, data)

    async def recover_stale(self, older_than_s: float) -> int:
        return await self._store.recover_stale(older_than_s)

    # --- outbox ----------------------------------------------------------

    async def claim_outbox(self) -> OutboxRecord | None:
        return await self._store.claim_outbox()

    async def mark_sent(self, outbox_id: int, turn_id: int | None, provider_message_id: str) -> None:
        await self._store.mark_sent(outbox_id, turn_id, provider_message_id)

    async def mark_send_failed(
        self, outbox_id: int, turn_id: int | None, error: str, retry_at: datetime | None
    ) -> None:
        await self._store.mark_send_failed(outbox_id, turn_id, error, retry_at)

    async def approve_outbox(self, outbox_id: int) -> bool:
        return await self._store.approve_outbox(outbox_id)

    # --- read-only views -------------------------------------------------

    async def list_conversations(self, limit: int) -> list[ConversationSummary]:
        return await self._store.list_conversations(limit)
