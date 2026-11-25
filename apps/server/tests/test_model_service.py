"""ModelService: the privacy gate, the single retry for invalid tool calls, and what is returned afterwards."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from yyai.core.config import ModelCapabilities, ModelRoleConfig
from yyai.core.errors import ConfigError, ExternalModelNotAllowed, IntegrationError
from yyai.core.types import ChatMessage, ModelReply, ToolCall, ToolSpec
from yyai.services.model import ModelService

ROLE = "chat.default"
TOOLS = [ToolSpec(name="quote_price", description="d", parameters={"type": "object"})]


class ScriptedModel:
    """A model server that answers from a list and remembers what it was asked."""

    def __init__(self, *replies: ModelReply) -> None:
        self._replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    async def chat(
        self,
        *,
        model: str,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        params: Mapping[str, Any],
        timeout_s: float,
    ) -> ModelReply:
        self.requests.append(
            {
                "model": model,
                "messages": list(messages),
                "tools": list(tools),
                "params": dict(params),
                "timeout_s": timeout_s,
            }
        )
        return self._replies.pop(0)


def role_config(**overrides: Any) -> ModelRoleConfig:
    values: dict[str, Any] = {
        "provider": "openai_compat",
        "base_url": "https://model.test/v1",
        "model": "qwen3.8-27b",
        "timeout_s": 42.0,
        "params": {"temperature": 0.3},
    }
    values.update(overrides)
    return ModelRoleConfig(**values)


def service(provider: ScriptedModel, **config: Any) -> ModelService:
    return ModelService({ROLE: role_config(**config)}, {ROLE: provider})


def tool_call(call_id: str, name: str = "quote_price", **arguments: Any) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments, raw_arguments="{}")


def validator(call: ToolCall) -> str | None:
    """Calls with a 'query' argument are valid; anything else is not."""
    return None if "query" in call.arguments else f"{call.name} needs a query"


USER = [ChatMessage(role="user", content="how much?")]


# --- the privacy gate -----------------------------------------------------------------


async def test_external_role_without_allow_external_is_refused_before_any_request() -> None:
    provider = ScriptedModel(ModelReply(text="hi"))
    with pytest.raises(ExternalModelNotAllowed):
        await service(provider, external=True, allow_external=False).chat(ROLE, USER, [])
    assert provider.requests == []


async def test_external_role_with_allow_external_is_used() -> None:
    provider = ScriptedModel(ModelReply(text="hi"))
    reply = await service(provider, external=True, allow_external=True).chat(ROLE, USER, [])
    assert reply.text == "hi"
    assert len(provider.requests) == 1


async def test_local_role_does_not_need_allow_external() -> None:
    provider = ScriptedModel(ModelReply(text="hi"))
    reply = await service(provider, external=False, allow_external=False).chat(ROLE, USER, [])
    assert reply.text == "hi"


async def test_unknown_role_is_a_config_error() -> None:
    with pytest.raises(ConfigError):
        await service(ScriptedModel()).chat("vision.default", USER, [])


async def test_tools_on_a_model_without_tool_support_is_a_config_error() -> None:
    provider = ScriptedModel(ModelReply(text="hi"))
    with pytest.raises(ConfigError):
        await service(provider, capabilities=ModelCapabilities(tools=False)).chat(ROLE, USER, TOOLS)
    assert provider.requests == []


async def test_role_settings_are_passed_to_the_provider() -> None:
    provider = ScriptedModel(ModelReply(text="hi"))
    await service(provider).chat(ROLE, USER, TOOLS)
    request = provider.requests[0]
    assert request["model"] == "qwen3.8-27b"
    assert request["params"] == {"temperature": 0.3}
    assert request["timeout_s"] == 42.0
    assert request["tools"] == TOOLS


# --- the retry for invalid tool calls --------------------------------------------------------


async def test_valid_tool_calls_are_not_retried() -> None:
    provider = ScriptedModel(ModelReply(tool_calls=[tool_call("c1", query="coffee")]))
    reply = await service(provider).chat(ROLE, USER, TOOLS, validate=validator)
    assert len(provider.requests) == 1
    assert [c.id for c in reply.tool_calls] == ["c1"]


async def test_without_a_validator_nothing_is_checked_or_retried() -> None:
    provider = ScriptedModel(ModelReply(tool_calls=[tool_call("c1")]))
    reply = await service(provider).chat(ROLE, USER, TOOLS)
    assert len(provider.requests) == 1
    assert len(reply.tool_calls) == 1


async def test_one_retry_on_an_invalid_tool_call_then_success() -> None:
    bad = tool_call("bad")  # no 'query'
    provider = ScriptedModel(
        ModelReply(text="let me check", tool_calls=[bad], usage={"prompt_tokens": 10, "total_tokens": 12}),
        ModelReply(
            tool_calls=[tool_call("good", query="coffee")], usage={"prompt_tokens": 20, "total_tokens": 25}
        ),
    )
    reply = await service(provider).chat(ROLE, USER, TOOLS, validate=validator)

    assert len(provider.requests) == 2
    assert [c.id for c in reply.tool_calls] == ["good"]
    # The cost of the retry is visible: usage is the sum of both requests.
    assert reply.usage == {"prompt_tokens": 30, "total_tokens": 37}

    retry_messages = provider.requests[1]["messages"]
    assert retry_messages[: len(USER)] == USER
    assistant, tool_message = retry_messages[-2], retry_messages[-1]
    assert assistant.role == "assistant"
    assert assistant.content == "let me check"
    assert assistant.tool_calls == [bad]
    assert tool_message.role == "tool"
    assert tool_message.tool_call_id == "bad"
    assert tool_message.content == "quote_price needs a query"


async def test_retry_message_marks_valid_calls_in_the_same_reply_as_not_executed() -> None:
    first = ModelReply(tool_calls=[tool_call("ok", query="a"), tool_call("bad"), tool_call("ok2", query="b")])
    provider = ScriptedModel(first, ModelReply(text="done"))
    await service(provider).chat(ROLE, USER, TOOLS, validate=validator)

    tool_messages = [m for m in provider.requests[1]["messages"] if m.role == "tool"]
    assert [m.tool_call_id for m in tool_messages] == ["ok", "bad", "ok2"]  # every call gets an answer
    assert tool_messages[0].content == "not executed: resend all calls corrected"
    assert tool_messages[1].content == "quote_price needs a query"
    assert tool_messages[2].content == "not executed: resend all calls corrected"


async def test_still_invalid_after_the_retry_drops_the_invalid_calls_and_keeps_the_text() -> None:
    provider = ScriptedModel(
        ModelReply(tool_calls=[tool_call("bad1")]),
        ModelReply(text="The price is 48 AED.", tool_calls=[tool_call("bad2")]),
    )
    reply = await service(provider).chat(ROLE, USER, TOOLS, validate=validator)
    assert len(provider.requests) == 2  # exactly one retry, never more
    assert reply.tool_calls == []
    assert reply.text == "The price is 48 AED."


async def test_still_invalid_after_the_retry_keeps_the_valid_calls() -> None:
    provider = ScriptedModel(
        ModelReply(tool_calls=[tool_call("bad1")]),
        ModelReply(tool_calls=[tool_call("bad2"), tool_call("good", query="coffee")]),
    )
    reply = await service(provider).chat(ROLE, USER, TOOLS, validate=validator)
    assert [c.id for c in reply.tool_calls] == ["good"]


async def test_nothing_left_after_the_retry_is_an_integration_error() -> None:
    provider = ScriptedModel(
        ModelReply(tool_calls=[tool_call("bad1")]), ModelReply(tool_calls=[tool_call("bad2")])
    )
    with pytest.raises(IntegrationError):
        await service(provider).chat(ROLE, USER, TOOLS, validate=validator)
    assert len(provider.requests) == 2


async def test_a_reply_with_no_text_and_no_tool_calls_is_an_integration_error() -> None:
    provider = ScriptedModel(ModelReply())
    with pytest.raises(IntegrationError):
        await service(provider).chat(ROLE, USER, TOOLS, validate=validator)


async def test_provider_errors_propagate() -> None:
    class Failing:
        async def chat(self, **_: Any) -> ModelReply:
            raise IntegrationError("down", retryable=True)

    with pytest.raises(IntegrationError):
        await ModelService({ROLE: role_config()}, {ROLE: Failing()}).chat(ROLE, USER, [])
