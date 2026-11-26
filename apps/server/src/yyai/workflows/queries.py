"""Read-only questions staff ask about customer chats, plus approving a held reply.

Internal chats (the staff Assistant page) are not customer chats: they are never listed, and asking for one by
id answers "not found".
"""

from __future__ import annotations

from yyai.core.errors import NotFound
from yyai.core.types import ConversationSummary, TranscriptMessage
from yyai.services.conversation import ConversationService


class ConversationQueries:
    def __init__(self, conversations: ConversationService) -> None:
        self._conversations = conversations

    async def list_conversations(self, limit: int, query: str | None = None) -> list[ConversationSummary]:
        return await self._conversations.list_conversations(limit, query)

    async def conversation(self, conversation_id: int) -> ConversationSummary:
        """One customer chat. Raises NotFound for an unknown or internal one."""
        found = await self._conversations.get_conversation(conversation_id)
        if found is None or found.internal:
            raise NotFound(f"No customer chat with id {conversation_id}")
        return found

    async def messages(
        self, conversation_id: int, limit: int, after_id: int | None = None
    ) -> list[TranscriptMessage]:
        """A customer chat's messages, oldest first. Raises NotFound for an unknown or internal chat."""
        await self.conversation(conversation_id)
        return await self._conversations.transcript(conversation_id, limit, after_id)

    async def approve(self, outbox_id: int) -> bool:
        """Release a reply that was waiting for staff. False if it was not waiting."""
        return await self._conversations.approve_outbox(outbox_id)
