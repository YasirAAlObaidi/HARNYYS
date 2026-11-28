"""ToolRegistry: what the model is told, how its calls are checked, and how tools are run safely."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel, Field

from yyai.core.errors import ConfigError, IntegrationError
from yyai.core.types import RunContext, ToolCall
from yyai.workflows.agent.registry import Tool, ToolRegistry


class EchoArgs(BaseModel):
    text: str = Field(min_length=1, description="What to echo")
    times: int = Field(1, ge=1, le=5)


class NoArgs(BaseModel):
    pass


class Quote(BaseModel):
    code: str
    price: Decimal


@pytest.fixture
def ctx() -> RunContext:
    return RunContext(
        turn_id=1,
        conversation_id=1,
        channel="whatsapp",
        customer_id="971501234567",
        customer_name="Ahmed",
        client_name="Kahraman",
        currency="AED",
        auto_send=True,
    )


@pytest.fixture
def calls_made() -> list[str]:
    return []


@pytest.fixture
def registry(calls_made: list[str]) -> ToolRegistry:
    async def echo(ctx: RunContext, args: EchoArgs) -> dict[str, Any]:
        calls_made.append("echo")
        return {"echo": args.text * args.times, "customer": ctx.customer_id}

    async def nothing(ctx: RunContext, args: NoArgs) -> list[str]:
        return []

    async def slow(ctx: RunContext, args: NoArgs) -> str:
        await asyncio.sleep(5)
        return "too late"

    async def big(ctx: RunContext, args: NoArgs) -> str:
        return "x" * 10_000

    async def write_something(ctx: RunContext, args: NoArgs) -> str:
        calls_made.append("write_something")
        return "written"

    async def boom(ctx: RunContext, args: NoArgs) -> str:
        raise RuntimeError("secret internal detail: db password is hunter2")

    async def erp_down(ctx: RunContext, args: NoArgs) -> str:
        raise IntegrationError("ERP unreachable")

    async def quote(ctx: RunContext, args: NoArgs) -> Quote:
        return Quote(code="SAMPLE-002", price=Decimal("135.50"))

    reg = ToolRegistry()
    reg.register(Tool("echo", "Echo text back", EchoArgs, "read", echo))
    reg.register(Tool("nothing", "Takes no arguments", NoArgs, "read", nothing))
    reg.register(Tool("slow", "Never finishes in time", NoArgs, "read", slow, timeout_s=0.05))
    reg.register(Tool("big", "Returns a huge result", NoArgs, "read", big, max_result_chars=100))
    reg.register(Tool("write_something", "Changes things", NoArgs, "write", write_something))
    reg.register(Tool("send_something", "Sends things", NoArgs, "send", write_something))
    reg.register(Tool("draft_something", "Drafts things", NoArgs, "draft", write_something))
    reg.register(Tool("boom", "Crashes", NoArgs, "read", boom))
    reg.register(Tool("erp_down", "Fails like a vendor", NoArgs, "read", erp_down))
    reg.register(Tool("quote", "Returns a model", NoArgs, "read", quote))
    return reg


def call(name: str, arguments: dict[str, Any] | None = None, raw: str | None = None) -> ToolCall:
    arguments = arguments or {}
    return ToolCall(
        id="call_1",
        name=name,
        arguments=arguments,
        raw_arguments=raw if raw is not None else json.dumps(arguments),
    )


# --- specs ------------------------------------------------------------------------


def test_specs_describe_every_tool_with_a_json_schema(registry: ToolRegistry) -> None:
    specs = {spec.name: spec for spec in registry.specs()}
    # write_something, send_something and draft_something need confirmation by default, so they are not offered.
    assert set(specs) == {"echo", "nothing", "slow", "big", "boom", "erp_down", "quote"}
    echo = specs["echo"]
    assert echo.description == "Echo text back"
    assert echo.parameters["type"] == "object"
    assert echo.parameters["required"] == ["text"]
    assert echo.parameters["properties"]["text"]["description"] == "What to echo"
    assert echo.parameters["properties"]["times"]["maximum"] == 5
    assert specs["nothing"].parameters["properties"] == {}


def test_registering_the_same_name_twice_is_a_config_error(registry: ToolRegistry) -> None:
    async def other(ctx: RunContext, args: NoArgs) -> None: ...

    with pytest.raises(ConfigError):
        registry.register(Tool("echo", "again", NoArgs, "read", other))


# --- validate ------------------------------------------------------------------------


def test_validate_accepts_a_good_call(registry: ToolRegistry) -> None:
    assert registry.validate(call("echo", {"text": "hi", "times": 2})) is None
    assert registry.validate(call("nothing")) is None


def test_validate_unknown_tool_names_the_tool_and_lists_the_real_ones(registry: ToolRegistry) -> None:
    problem = registry.validate(call("delete_everything"))
    assert problem is not None
    assert "unknown tool 'delete_everything'" in problem
    assert "echo" in problem
    assert "quote" in problem


def test_validate_missing_required_argument(registry: ToolRegistry) -> None:
    problem = registry.validate(call("echo", {}))
    assert problem is not None
    assert "invalid arguments for 'echo'" in problem
    assert "text" in problem


@pytest.mark.parametrize(
    "arguments",
    [{"text": "hi", "times": "many"}, {"text": "hi", "times": 0}, {"text": "hi", "times": 6}, {"text": ""}],
)
def test_validate_bad_argument_values(registry: ToolRegistry, arguments: dict[str, Any]) -> None:
    problem = registry.validate(call("echo", arguments))
    assert problem is not None
    assert "invalid arguments for 'echo'" in problem


def test_validate_arguments_that_were_not_a_json_object(registry: ToolRegistry) -> None:
    # The handler turned unparsable arguments into {} and kept the raw text.
    problem = registry.validate(call("echo", {}, raw='{"text": "hi", '))
    assert problem is not None
    assert "must be a JSON object" in problem


def test_validate_empty_object_is_fine_for_a_tool_without_arguments(registry: ToolRegistry) -> None:
    assert registry.validate(call("nothing", {}, raw="{}")) is None
    assert registry.validate(call("nothing", {}, raw="null")) is None
    assert registry.validate(call("nothing", {}, raw="")) is None


def test_validate_extra_arguments_do_not_break_a_call(registry: ToolRegistry) -> None:
    assert registry.validate(call("echo", {"text": "hi", "colour": "red"})) is None


# --- run ----------------------------------------------------------------------------------


async def test_run_returns_the_result_as_json_text(registry: ToolRegistry, ctx: RunContext) -> None:
    result = await registry.run(call("echo", {"text": "قهوة ", "times": 2}), ctx)
    assert json.loads(result) == {"echo": "قهوة قهوة ", "customer": "971501234567"}
    assert "قهوة" in result  # Arabic is not escaped, so the model sees real text


async def test_run_tools_see_the_context_set_by_our_code(registry: ToolRegistry, ctx: RunContext) -> None:
    other = ctx.model_copy(update={"customer_id": "971509999999"})
    result = json.loads(await registry.run(call("echo", {"text": "x"}), other))
    assert result["customer"] == "971509999999"


async def test_run_serialises_pydantic_models_and_decimals(registry: ToolRegistry, ctx: RunContext) -> None:
    assert json.loads(await registry.run(call("quote"), ctx)) == {"code": "SAMPLE-002", "price": "135.50"}


async def test_run_unknown_tool_returns_a_json_error(registry: ToolRegistry, ctx: RunContext) -> None:
    result = json.loads(await registry.run(call("nope"), ctx))
    assert "unknown tool 'nope'" in result["error"]


async def test_run_bad_arguments_return_a_json_error_and_never_run_the_tool(
    registry: ToolRegistry, ctx: RunContext, calls_made: list[str]
) -> None:
    result = json.loads(await registry.run(call("echo", {"times": 2}), ctx))
    assert "invalid arguments" in result["error"]
    assert calls_made == []


async def test_run_timeout_returns_a_json_error(registry: ToolRegistry, ctx: RunContext) -> None:
    result = json.loads(await asyncio.wait_for(registry.run(call("slow"), ctx), timeout=2))
    assert "timed out" in result["error"]
    assert "slow" in result["error"]


@pytest.mark.parametrize("tool", ["write_something", "send_something", "draft_something"])
async def test_run_refuses_anything_that_is_not_read_only(
    registry: ToolRegistry, ctx: RunContext, calls_made: list[str], tool: str
) -> None:
    result = json.loads(await registry.run(call(tool), ctx))
    assert "needs confirmation" in result["error"]
    assert calls_made == []  # the function never ran


async def test_run_truncates_a_huge_result(registry: ToolRegistry, ctx: RunContext) -> None:
    result = await registry.run(call("big"), ctx)
    assert len(result) == 100
    assert result.endswith("...[truncated]")


async def test_run_small_result_is_not_truncated(registry: ToolRegistry, ctx: RunContext) -> None:
    result = await registry.run(call("echo", {"text": "x"}), ctx)
    assert "truncated" not in result


async def test_run_reports_our_own_errors_with_their_message(registry: ToolRegistry, ctx: RunContext) -> None:
    result = json.loads(await registry.run(call("erp_down"), ctx))
    assert result["error"] == "tool 'erp_down' failed: ERP unreachable"


async def test_run_never_raises_and_never_leaks_the_message_of_an_unexpected_crash(
    registry: ToolRegistry, ctx: RunContext
) -> None:
    result = await registry.run(call("boom"), ctx)
    assert json.loads(result) == {"error": "tool 'boom' failed unexpectedly"}
    assert "hunter2" not in result
