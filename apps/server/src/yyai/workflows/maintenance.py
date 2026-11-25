"""Upkeep: re-queue work cut off by a crash, and report whether the system is healthy."""

from __future__ import annotations

import logging
from typing import Any

from yyai.services.conversation import ConversationService

logger = logging.getLogger(__name__)


class MaintenanceWorkflow:
    def __init__(self, conversations: ConversationService, stale_after_s: float) -> None:
        self._conversations = conversations
        self._stale_after_s = stale_after_s

    async def recover(self) -> int:
        """Put turns and sends that were cut off back in the queue. Returns how many were touched."""
        count = await self._conversations.recover_stale(self._stale_after_s)
        if count:
            logger.warning("Recovered %s stale turn(s) or send(s)", count)
        return count

    async def health(self) -> dict[str, Any]:
        try:
            await self._conversations.ping()
        except Exception as exc:  # noqa: BLE001 - any failure at all means unhealthy
            logger.warning("Health check: database unreachable: %s", exc)
            return {"status": "error", "database": f"{type(exc).__name__}: {str(exc)[:200]}"}
        return {"status": "ok", "database": "ok"}
