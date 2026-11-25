"""The jobs: what can be asked of the outside world, and what comes back.

Services depend only on these interfaces. Each brand handler (one folder per
product under `integrations/`) implements one or more of them. Which brand fills
which job is decided by the client's config, in `yyai.bootstrap`.
See docs/decisions/0005.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from yyai.core.types import (
    CatalogueItem,
    ChatMessage,
    InboundMessage,
    ItemPrice,
    ModelReply,
    SendResult,
    StockLevel,
    ToolSpec,
)


@runtime_checkable
class InventoryPort(Protocol):
    """Items, prices and stock. Filled by Al Ameen, or by a file for demos."""

    async def list_items(self) -> list[CatalogueItem]: ...

    async def get_prices(self, codes: Sequence[str]) -> dict[str, ItemPrice]: ...

    async def get_stock(self, codes: Sequence[str]) -> dict[str, StockLevel]: ...


@runtime_checkable
class MessagingPort(Protocol):
    """A channel customers write on: WhatsApp, web chat, later email."""

    def verify_subscription(self, params: Mapping[str, str]) -> str | None:
        """Answer a provider's webhook handshake. Returns the challenge, or None to refuse."""
        ...

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> list[InboundMessage]:
        """Check the signature and turn the provider's payload into our messages."""
        ...

    async def send_text(self, to: str, text: str) -> SendResult: ...

    def freeform_allowed(self, last_inbound_at: datetime | None) -> bool:
        """False when the provider only allows template messages (WhatsApp's 24-hour rule)."""
        ...


@runtime_checkable
class ChatModelPort(Protocol):
    """A model server: TensorFold, vLLM, Ollama, llama.cpp, a hosted API."""

    async def chat(
        self,
        *,
        model: str,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        params: Mapping[str, Any],
        timeout_s: float,
    ) -> ModelReply: ...
