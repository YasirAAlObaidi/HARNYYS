"""The staff Assistant page: a member of staff chats with the same agent customers reach.

Each staff user has one conversation on the built-in `staff` channel. A message is saved and its turn queued
exactly like a customer's, so the worker answers it with the same prompt, tools and product table. The
conversation is marked internal: it never shows on the Chats page, never counts in Insights, and the agent's
RunContext has `internal` set, so a tool that records something real (a quote request) can refuse to.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from yyai.core.types import STAFF_CHANNEL, InboundMessage, StaffUser
from yyai.services.conversation import ConversationService

MAX_MESSAGE_CHARS = 2000
HISTORY_LIMIT = 200


def staff_sender_id(user: StaffUser) -> str:
    return f"staff-{user.id}"


class AssistantWorkflow:
    def __init__(self, conversations: ConversationService) -> None:
        self._conversations = conversations

    async def send(self, user: StaffUser, text: str, client_id: str | None = None) -> dict[str, Any]:
        """Save the message and queue a turn. `client_id` makes a retried send harmless (it is stored once).

        Raises ValueError for an empty or too-long message.
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("The message is empty")
        if len(text) > MAX_MESSAGE_CHARS:
            raise ValueError(f"The message is longer than {MAX_MESSAGE_CHARS} characters")
        message = InboundMessage(
            channel=STAFF_CHANNEL,
            source_id=f"staff-{(client_id or uuid.uuid4().hex)[:64]}",
            sender_id=staff_sender_id(user),
            sender_name=user.display_name or user.username,
            text=text,
            received_at=datetime.now(UTC),
            internal=True,
        )
        result = await self._conversations.record_inbound([message])
        return {"queued": result["new"] == 1}

    async def history(self, user: StaffUser, after_id: int | None = None) -> dict[str, Any]:
        """This user's assistant chat, and whether a reply is still being written."""
        conversation_id = await self._conversations.find_conversation(STAFF_CHANNEL, staff_sender_id(user))
        if conversation_id is None:
            return {"messages": [], "pending": False}
        messages = await self._conversations.transcript(conversation_id, HISTORY_LIMIT, after_id)
        return {
            "messages": [m.model_dump(mode="json") for m in messages],
            "pending": await self._conversations.has_pending_turn(conversation_id),
        }
