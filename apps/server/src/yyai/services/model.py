"""Model access: picks the role's model server, enforces the privacy rules, repairs bad tool calls.

Services never name a model product. Which server answers a role comes from the
client's config; this service only checks that using it is allowed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from yyai.core.config import ModelRoleConfig
from yyai.core.errors import ConfigError, ExternalModelNotAllowed, IntegrationError
from yyai.core.types import ChatMessage, ModelReply, ToolCall, ToolSpec
from yyai.handlers.ports import ChatModelPort

logger = logging.getLogger(__name__)

_NOT_EXECUTED = "not executed: resend all calls corrected"

Validator = Callable[[ToolCall], str | None]


class ModelService:
    def __init__(self, roles: dict[str, ModelRoleConfig], providers: dict[str, ChatModelPort]) -> None:
        self._roles = roles
        self._providers = providers  # keyed by role name

    async def chat(
        self,
        role: str,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        validate: Validator | None = None,
    ) -> ModelReply:
        config = self._roles.get(role)
        provider = self._providers.get(role)
        if config is None or provider is None:
            raise ConfigError(f"No model is configured for role '{role}'")
        if config.external and not config.allow_external:
            raise ExternalModelNotAllowed(
                f"Role '{role}' points outside the building ({config.base_url}) "
                "but the client has not allowed external models"
            )
        if tools and not config.capabilities.tools:
            raise ConfigError(f"Role '{role}' is configured without tool support, but tools were given")

        async def call(history: Sequence[ChatMessage]) -> ModelReply:
            return await provider.chat(
                model=config.model,
                messages=history,
                tools=tools,
                params=config.params,
                timeout_s=config.timeout_s,
            )

        reply = await call(messages)
        if validate is not None and reply.tool_calls:
            errors = _validation_errors(reply.tool_calls, validate)
            if errors:
                logger.info("Model sent %d invalid tool call(s) on role %s; retrying once", len(errors), role)
                retry_messages = [
                    *messages,
                    ChatMessage(role="assistant", content=reply.text, tool_calls=reply.tool_calls),
                    *(
                        ChatMessage(
                            role="tool",
                            content=errors.get(index) or _NOT_EXECUTED,
                            tool_call_id=call.id,
                            name=call.name,
                        )
                        for index, call in enumerate(reply.tool_calls)
                    ),
                ]
                retried = await call(retry_messages)
                reply = retried.model_copy(update={"usage": _sum_usage(reply.usage, retried.usage)})
                reply = _drop_invalid(reply, validate)
        if not reply.tool_calls and not reply.text:
            raise IntegrationError("model produced no valid answer")
        return reply


def _validation_errors(calls: Sequence[ToolCall], validate: Validator) -> dict[int, str]:
    """Map the position of each invalid call to what is wrong with it."""
    errors: dict[int, str] = {}
    for index, call in enumerate(calls):
        problem = validate(call)
        if problem:
            errors[index] = problem
    return errors


def _drop_invalid(reply: ModelReply, validate: Validator) -> ModelReply:
    valid = [call for call in reply.tool_calls if validate(call) is None]
    if len(valid) == len(reply.tool_calls):
        return reply
    logger.warning(
        "Dropping %d tool call(s) that are still invalid after one retry", len(reply.tool_calls) - len(valid)
    )
    return reply.model_copy(update={"tool_calls": valid})


def _sum_usage(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Add up the numeric counters of two replies so the audit log shows the true cost of a retry."""
    merged: dict[str, Any] = dict(second)
    for key, value in first.items():
        other = merged.get(key)
        if isinstance(value, int | float) and isinstance(other, int | float) and not isinstance(value, bool):
            merged[key] = value + other
        elif key not in merged:
            merged[key] = value
    return merged
