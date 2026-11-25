"""Messaging: one place that knows which channel is which, and the sending rules."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from yyai.core.errors import NotFound, WindowClosed
from yyai.core.types import InboundMessage, SendResult
from yyai.handlers.ports import MessagingPort


class MessagingService:
    def __init__(self, channels: dict[str, MessagingPort]) -> None:
        self._channels = channels

    def _channel(self, name: str) -> MessagingPort:
        try:
            return self._channels[name]
        except KeyError:
            raise NotFound(f"Unknown channel: {name}") from None

    def verify(self, channel: str, params: Mapping[str, str]) -> str | None:
        """Answer a provider's webhook handshake. None means refuse."""
        return self._channel(channel).verify_subscription(params)

    def parse(self, channel: str, headers: Mapping[str, str], body: bytes) -> list[InboundMessage]:
        """Check the signature and turn the provider's payload into our messages."""
        return self._channel(channel).parse_webhook(headers, body)

    async def send(self, channel: str, to: str, text: str, last_inbound_at: datetime | None) -> SendResult:
        port = self._channel(channel)
        if not port.freeform_allowed(last_inbound_at):
            raise WindowClosed(f"Channel {channel} only allows template messages to {to} right now")
        return await port.send_text(to, text)
