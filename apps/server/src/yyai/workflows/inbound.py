"""Inbound messages: check them, save them, queue a turn. Nothing slow happens here.

The webhook route needs no staff login, so only channels whose webhooks carry a signature we check (WhatsApp)
are reachable through it. Every other channel answers "not found" there. The staff Assistant page has its own
logged-in route instead (workflows/assistant.py).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from yyai.core.errors import NotFound, SignatureError, YyaiError
from yyai.services.conversation import ConversationService
from yyai.services.messaging import MessagingService


class InvalidPayload(YyaiError, ValueError):
    """The provider sent something we cannot read as messages."""


class InboundWorkflow:
    def __init__(
        self,
        messaging: MessagingService,
        conversations: ConversationService,
        webhook_channels: Collection[str],
    ) -> None:
        self._messaging = messaging
        self._conversations = conversations
        self._webhook_channels = frozenset(webhook_channels)

    def _check_public(self, channel: str) -> None:
        if channel not in self._webhook_channels:
            raise NotFound(f"Unknown channel: {channel}")

    def verify(self, channel: str, params: Mapping[str, str]) -> str | None:
        """Answer a provider's webhook handshake. None means refuse it. Raises NotFound for other channels."""
        self._check_public(channel)
        return self._messaging.verify(channel, params)

    async def accept(self, channel: str, headers: Mapping[str, str], body: bytes) -> dict[str, int]:
        """Check the signature, store new messages and queue their turns.

        Raises SignatureError, NotFound (unknown or non-public channel) or InvalidPayload (a ValueError).
        """
        self._check_public(channel)
        try:
            messages = self._messaging.parse(channel, headers, body)
        except (SignatureError, NotFound, InvalidPayload):
            raise
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            # Includes bad JSON and pydantic validation errors, which are ValueErrors.
            raise InvalidPayload(f"Cannot read the {channel} webhook payload: {exc}") from exc
        # A provider can never create an internal chat: only the logged-in Assistant route may.
        for message in messages:
            message.internal = False
        return await self._conversations.record_inbound(messages)
