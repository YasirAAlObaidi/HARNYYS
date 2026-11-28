"""Outbox delivery: send queued replies, retry the ones that fail for a good reason."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from yyai.core.errors import IntegrationError, NotFound, WindowClosed
from yyai.core.types import OutboxRecord
from yyai.services.conversation import ConversationService
from yyai.services.messaging import MessagingService

logger = logging.getLogger(__name__)

RETRY_BASE_S = 5.0
RETRY_MAX_S = 600.0


class OutboxWorkflow:
    def __init__(
        self, conversations: ConversationService, messaging: MessagingService, max_attempts: int
    ) -> None:
        self._conversations = conversations
        self._messaging = messaging
        self._max_attempts = max_attempts

    async def deliver_once(self) -> bool:
        """Send one waiting reply. Returns False when the outbox had nothing ready."""
        record = await self._conversations.claim_outbox()
        if record is None:
            return False
        try:
            if record.kind == "image" and record.image_url:
                result = await self._messaging.send_image(
                    record.channel, record.to, record.image_url, record.text, record.last_inbound_at
                )
            else:
                result = await self._messaging.send(
                    record.channel, record.to, record.text, record.last_inbound_at
                )
        except WindowClosed as exc:
            # Only template messages are allowed now; waiting will not change that.
            logger.warning("Outbox %s not sent: %s", record.id, exc)
            await self._conversations.mark_send_failed(record.id, record.turn_id, str(exc), None)
        except NotFound as exc:
            # The channel is not in this install's config. Retrying cannot fix that.
            logger.error("Outbox %s not sent: %s", record.id, exc)
            await self._conversations.mark_send_failed(record.id, record.turn_id, str(exc), None)
        except IntegrationError as exc:
            await self._fail(record, exc, retryable=exc.retryable)
        except Exception as exc:
            logger.exception("Outbox %s: unexpected error while sending", record.id)
            await self._fail(record, exc, retryable=True)
        else:
            await self._conversations.mark_sent(record.id, record.turn_id, result.provider_message_id)
        return True

    async def _fail(self, record: OutboxRecord, exc: Exception, *, retryable: bool) -> None:
        message = f"{type(exc).__name__}: {exc}"
        if retryable and record.attempts < self._max_attempts:
            delay = min(RETRY_BASE_S * 2**record.attempts, RETRY_MAX_S)
            retry_at = datetime.now(UTC) + timedelta(seconds=delay)
            logger.warning(
                "Outbox %s send failed (attempt %s), retrying in %ss: %s",
                record.id,
                record.attempts,
                delay,
                exc,
            )
            await self._conversations.mark_send_failed(record.id, record.turn_id, message, retry_at)
        else:
            logger.error(
                "Outbox %s send failed for good after %s attempt(s): %s", record.id, record.attempts, exc
            )
            await self._conversations.mark_send_failed(record.id, record.turn_id, message, None)
