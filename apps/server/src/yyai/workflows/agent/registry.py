"""The tool registry: what the model may call, checked and run by our code.

Each tool is fixed code we wrote. The model chooses a tool and its arguments;
everything about who the customer is comes from the RunContext, which the model
cannot change (docs/decisions/0008).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from yyai.core.errors import ConfigError, YyaiError
from yyai.core.types import RunContext, ToolCall, ToolSpec

logger = logging.getLogger(__name__)

Risk = Literal["read", "draft", "send", "write"]


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    risk: Risk
    fn: Callable[[RunContext, Any], Awaitable[Any]]
    timeout_s: float = 15.0
    max_result_chars: int = 4000


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ConfigError(f"Tool '{tool.name}' is registered twice")
        self._tools[tool.name] = tool

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=tool.name, description=tool.description, parameters=tool.args_model.model_json_schema()
            )
            for tool in self._tools.values()
        ]

    def validate(self, call: ToolCall) -> str | None:
        """Return a short message the model can act on, or None when the call is fine."""
        return self._check(call)[1]

    async def run(self, call: ToolCall, ctx: RunContext) -> str:
        """Run one tool call and return its result as JSON text. Never raises."""
        try:
            tool, problem, args = self._check(call)
            if problem or tool is None or args is None:
                return _error_json(problem or "invalid call")
            if tool.risk != "read":
                # Confirmations are not built yet, so nothing that changes or sends anything may run.
                return _error_json(f"tool '{tool.name}' needs confirmation, which is not available yet")
            result = await asyncio.wait_for(tool.fn(ctx, args), timeout=tool.timeout_s)
            return _to_json(result, tool.max_result_chars)
        except TimeoutError:
            logger.warning("Tool %s timed out", call.name)
            return _error_json(f"tool '{call.name}' timed out; try again or answer without it")
        except YyaiError as exc:
            logger.warning("Tool %s failed: %s", call.name, exc)
            return _error_json(f"tool '{call.name}' failed: {exc}"[:300])
        except Exception:
            logger.exception("Tool %s crashed", call.name)
            return _error_json(f"tool '{call.name}' failed unexpectedly")

    # --- helpers ---------------------------------------------------------

    def _check(self, call: ToolCall) -> tuple[Tool | None, str | None, BaseModel | None]:
        tool = self._tools.get(call.name)
        if tool is None:
            known = ", ".join(self._tools) or "none"
            return None, f"unknown tool '{call.name}'. Available tools: {known}", None
        if call.raw_arguments is not None and not call.arguments and not _is_empty_object(call.raw_arguments):
            return tool, f"arguments for '{call.name}' must be a JSON object", None
        try:
            return tool, None, tool.args_model.model_validate(call.arguments)
        except ValidationError as exc:
            return tool, f"invalid arguments for '{call.name}': {_summarise(exc)}", None


def _is_empty_object(raw: str) -> bool:
    try:
        return json.loads(raw or "{}") in ({}, None)
    except json.JSONDecodeError:
        return False


def _summarise(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors()[:4]:
        where = ".".join(str(part) for part in error["loc"]) or "arguments"
        parts.append(f"{where}: {error['msg']}")
    return "; ".join(parts)


def _error_json(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return str(value)


def _to_json(result: Any, max_chars: int) -> str:
    text = json.dumps(result, ensure_ascii=False, default=_json_default)
    if len(text) <= max_chars:
        return text
    marker = "...[truncated]"
    return text[: max(0, max_chars - len(marker))] + marker
