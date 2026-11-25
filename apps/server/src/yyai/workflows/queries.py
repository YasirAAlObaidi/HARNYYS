"""Read-only questions staff ask about conversations, plus approving a held reply."""

from __future__ import annotations

from yyai.core.types import ConversationSummary, StoredMessage
from yyai.services.conversation import ConversationService


class ConversationQueries:
    def __init__(self, conversations: ConversationService) -> None:
        self._conversations = conversations

    async def list_conversations(self, limit: int) -> list[ConversationSummary]:
        return await self._conversations.list_conversations(limit)

    async def messages(self, conversation_id: int, limit: int) -> list[StoredMessage]:
        return await self._conversations.history(conversation_id, limit)

    async def approve(self, outbox_id: int) -> bool:
        """Release a reply that was waiting for staff. False if it was not waiting."""
        return await self._conversations.approve_outbox(outbox_id)
