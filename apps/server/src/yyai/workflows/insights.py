"""Insights: the worker computes a snapshot at the top of every hour; the API serves the latest one."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from yyai.services.insights import InsightService

logger = logging.getLogger(__name__)

MAX_AGE = timedelta(hours=1)
AFTER_THE_HOUR_S = 1.0  # wake just after the hour, never just before it


class InsightsWorkflow:
    def __init__(self, insights: InsightService) -> None:
        self._insights = insights
        # The next snapshot is due at the first full hour after the latest one. Kept as a wall-clock time, so a
        # run missed while the machine slept is seen as overdue and made at once.
        self._due_at: datetime | None = None

    async def refresh(self) -> None:
        snapshot = await self._insights.refresh()
        self._due_at = self._insights.next_refresh_at(snapshot.computed_at)
        logger.info("Insights snapshot %s computed at %s", snapshot.id, snapshot.computed_at.isoformat())

    async def refresh_if_stale(self) -> bool:
        """At worker start: compute a snapshot now unless the latest is less than an hour old. True if it did."""
        latest = await self._insights.latest()
        if latest is not None and not self._insights.is_stale(latest, MAX_AGE):
            self._due_at = self._insights.next_refresh_at(latest.computed_at)
            return False
        await self.refresh()
        return True

    def seconds_until_next_refresh(self) -> float:
        """0 plus a second's margin when a snapshot is due or overdue."""
        now = self._insights.now()
        due = self._due_at or self._insights.next_refresh_at(now)
        return max(0.0, (due - now).total_seconds()) + AFTER_THE_HOUR_S

    async def latest(self) -> dict[str, Any] | None:
        """The newest snapshot as the web app reads it, or None before the first one exists."""
        snapshot = await self._insights.latest()
        if snapshot is None:
            return None
        computed_at = snapshot.computed_at.astimezone(self._insights.timezone)
        return {
            **snapshot.data,
            "id": snapshot.id,
            "computed_at": computed_at.isoformat(),
            "next_at": self._insights.next_refresh_at(snapshot.computed_at).isoformat(),
        }
