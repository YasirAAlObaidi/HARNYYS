"""Web chat brand: lets staff (or a demo screen) talk to the agent from our own web app.

There is no outside provider. Inbound messages are posted as JSON to our API on
the office network, and replies are read back from our database by the web app.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from yyai.core.types import InboundMessage, SendResult


class WebChat:
    def __init__(self, *, channel: str) -> None:
        self.channel = channel

    def verify_subscription(self, params: Mapping[str, str]) -> str | None:
        return None

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> list[InboundMessage]:
        data = json.loads(body or b"{}")
        text = str(data.get("text", "")).strip()
        user_id = str(data.get("user_id", "")).strip()
        if not text or not user_id:
            return []
        return [
            InboundMessage(
                channel=self.channel,
                source_id=str(data.get("message_id") or uuid.uuid4().hex),
                sender_id=user_id,
                sender_name=data.get("name"),
                text=text,
                received_at=datetime.now(UTC),
            )
        ]

    def freeform_allowed(self, last_inbound_at: datetime | None) -> bool:
        return True

    async def send_text(self, to: str, text: str) -> SendResult:
        # Nothing to deliver: the web app reads replies from our database.
        return SendResult(provider_message_id=f"webchat-{uuid.uuid4().hex[:16]}")
