"""One agent turn: claim a received message, let the model use tools, queue the reply.

Runs only in the worker (docs/decisions/0007). The loop is deliberately small:
ask the model, run the tools it called, ask again, until it answers in text or
runs out of steps. Everything is written to the audit log as it happens.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from yyai.core.config import AgentConfig, ClientConfig
from yyai.core.errors import IntegrationError
from yyai.core.types import ChatMessage, Direction, RunContext, TurnRecord
from yyai.services.conversation import ConversationService
from yyai.services.model import ModelService
from yyai.workflows.agent.registry import ToolRegistry

logger = logging.getLogger(__name__)

AUDIT_RESULT_CHARS = 2000

OUT_OF_STEPS_NOTE = (
    "You have used all the tool steps you were allowed. Do not call any more tools. "
    "Using only what you have already found, write your final answer to the customer now. "
    "If something could not be checked, say so plainly and do not guess."
)


@dataclass
class _Progress:
    steps: int = 0


class _KeepUnknown(dict):
    """Lets `{unknown}` stay as written when a prompt is formatted."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class AgentTurnWorkflow:
    def __init__(
        self,
        conversations: ConversationService,
        model: ModelService,
        registry: ToolRegistry,
        agent: AgentConfig,
        client: ClientConfig,
        role: str = "chat.default",
    ) -> None:
        self._conversations = conversations
        self._model = model
        self._registry = registry
        self._agent = agent
        self._client = client
        self._role = role

    async def run_once(self) -> bool:
        """Handle at most one waiting turn. Returns False when there was nothing to do."""
        turn = await self._conversations.claim_turn()
        if turn is None:
            return False
        progress = _Progress()
        try:
            reply = await self._run(turn, progress)
            await self._conversations.finish_turn(
                turn.id, turn.conversation_id, reply, auto_send=self._agent.auto_send, steps=progress.steps
            )
        except Exception as exc:
            logger.exception("Turn %s failed", turn.id)
            await self._handle_failure(turn, exc, progress.steps)
        return True

    # --- the loop --------------------------------------------------------

    async def _run(self, turn: TurnRecord, progress: _Progress) -> str:
        ctx = RunContext(
            turn_id=turn.id,
            conversation_id=turn.conversation_id,
            channel=turn.channel,
            customer_id=turn.external_user_id,
            customer_name=turn.customer_name,
            client_name=self._client.name,
            currency=self._client.currency,
            auto_send=self._agent.auto_send,
        )
        history = await self._conversations.history(turn.conversation_id, self._agent.history_messages)
        messages = [ChatMessage(role="system", content=self._system_prompt())]
        messages.extend(
            ChatMessage(
                role="user" if stored.direction == Direction.INBOUND else "assistant", content=stored.text
            )
            for stored in history
        )
        specs = self._registry.specs()

        for _ in range(self._agent.max_steps):
            progress.steps += 1
            reply = await self._model.chat(self._role, messages, specs, validate=self._registry.validate)
            await self._conversations.audit(
                turn.id,
                "model_reply",
                self._role,
                {
                    "step": progress.steps,
                    "text": reply.text,
                    "tool_calls": [call.name for call in reply.tool_calls],
                    "usage": reply.usage,
                },
            )
            if not reply.tool_calls:
                return _require_text(reply.text)
            messages.append(ChatMessage(role="assistant", content=reply.text, tool_calls=reply.tool_calls))
            for call in reply.tool_calls:
                result = await self._registry.run(call, ctx)
                await self._conversations.audit(
                    turn.id,
                    "tool_call",
                    call.name,
                    {"step": progress.steps, "args": call.arguments, "result": result[:AUDIT_RESULT_CHARS]},
                )
                messages.append(
                    ChatMessage(role="tool", content=result, tool_call_id=call.id, name=call.name)
                )

        # Out of steps: ask once more, without tools, for an answer from what was found.
        progress.steps += 1
        messages.append(ChatMessage(role="system", content=OUT_OF_STEPS_NOTE))
        reply = await self._model.chat(self._role, messages, [])
        await self._conversations.audit(
            turn.id,
            "model_reply",
            self._role,
            {"step": progress.steps, "final": True, "text": reply.text, "usage": reply.usage},
        )
        return _require_text(reply.text)

    def _system_prompt(self) -> str:
        values = _KeepUnknown(
            client_name=self._client.name, currency=self._client.currency, today=self._today()
        )
        try:
            return self._agent.system_prompt.format_map(values)
        except (ValueError, IndexError, AttributeError, KeyError):
            # A stray brace in the prompt: fall back to replacing just our three names.
            prompt = self._agent.system_prompt
            for key, value in values.items():
                prompt = prompt.replace("{" + key + "}", value)
            return prompt

    def _today(self) -> str:
        try:
            now = datetime.now(ZoneInfo(self._client.timezone))
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning("Unknown timezone %r, using UTC for the date", self._client.timezone)
            now = datetime.now(UTC)
        return f"{now:%A} {now.date().isoformat()}"

    # --- failure ---------------------------------------------------------

    async def _handle_failure(self, turn: TurnRecord, exc: Exception, steps: int) -> None:
        """Never lets an error escape: if even this fails, the turn stays 'running' and recovery re-queues it."""
        try:
            await self._conversations.audit(turn.id, "error", type(exc).__name__, {"error": str(exc)[:1000]})
            if self._agent.fallback_reply:
                await self._conversations.finish_turn(
                    turn.id,
                    turn.conversation_id,
                    self._agent.fallback_reply,
                    auto_send=self._agent.auto_send,
                    steps=steps,
                )
            else:
                await self._conversations.fail_turn(turn.id, f"{type(exc).__name__}: {exc}")
        except Exception:
            logger.exception("Could not record the failure of turn %s", turn.id)


def _require_text(text: str | None) -> str:
    if not text or not text.strip():
        raise IntegrationError("model gave no final answer")
    return text.strip()
