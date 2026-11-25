"""The finished set of workflows. Entry code (the API and the worker) receives one of these."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from yyai.workflows.agent.turn import AgentTurnWorkflow
from yyai.workflows.catalogue_sync import CatalogueSyncWorkflow
from yyai.workflows.inbound import InboundWorkflow
from yyai.workflows.maintenance import MaintenanceWorkflow
from yyai.workflows.outbox import OutboxWorkflow
from yyai.workflows.queries import ConversationQueries

logger = logging.getLogger(__name__)


@dataclass
class Workflows:
    inbound: InboundWorkflow
    turns: AgentTurnWorkflow
    outbox: OutboxWorkflow
    catalogue_sync: CatalogueSyncWorkflow
    maintenance: MaintenanceWorkflow
    queries: ConversationQueries
    # Called by aclose(), last registered first, so the database closes after the things that use it.
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)

    async def aclose(self) -> None:
        """Close connections and HTTP clients. One failing closer never stops the others."""
        for closer in reversed(self.closers):
            try:
                await closer()
            except Exception:
                logger.exception("Error while shutting down")
        self.closers.clear()
