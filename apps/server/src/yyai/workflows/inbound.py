"""Inbound messages: check them, save them, queue a turn. Nothing slow happens here."""

from __future__ import annotations

from collections.abc import Mapping

from yyai.core.errors import NotFound, SignatureError, YyaiError
from yyai.services.conversation import ConversationService
from yyai.services.messaging import MessagingService


class InvalidPayload(YyaiError, ValueError):
    """The provider sent something we cannot read as messages."""


class InboundWorkflow:
    def __init__(self, messaging: MessagingService, conversations: ConversationService) -> None:
        self._messaging = messaging
        self._conversations = conversations

    def verify(self, channel: str, params: Mapping[str, str]) -> str | None:
        """Answer a provider's webhook handshake. None means refuse it."""
        return self._messaging.verify(channel, params)

    async def accept(self, channel: str, headers: Mapping[str, str], body: bytes) -> dict[str, int]:
        """Check the signature, store new messages and queue their turns.

        Raises SignatureError, NotFound (unknown channel) or InvalidPayload (a ValueError).
        """
        try:
            messages = self._messaging.parse(channel, headers, body)
        except (SignatureError, NotFound, InvalidPayload):
            raise
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            # Includes bad JSON and pydantic validation errors, which are ValueErrors.
            raise InvalidPayload(f"Cannot read the {channel} webhook payload: {exc}") from exc
        return await self._conversations.record_inbound(messages)
