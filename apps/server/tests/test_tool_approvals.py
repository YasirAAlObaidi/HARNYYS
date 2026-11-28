"""Each tool's approval rule (docs/decisions/0008): the default comes from its risk class, the client's config can
set it per tool, and a tool that needs confirmation is neither offered to the model nor run."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from yyai.core.errors import ConfigError
from yyai.core.types import RunContext, ToolCall
from yyai.workflows.agent.registry import Risk, Tool, ToolRegistry

CTX = RunContext(
    turn_id=1,
    conversation_id=1,
    channel="whatsapp",
    customer_id="971500000000",
    customer_name=None,
    client_name="Kahraman",
    currency="AED",
    auto_send=True,
)


class NoArgs(BaseModel):
    pass


def tool(name: str, risk: Risk) -> Tool:
    async def fn(ctx: RunContext, args: NoArgs) -> dict[str, str]:
        return {"ran": name}

    return Tool(name=name, description=name, args_model=NoArgs, risk=risk, fn=fn)


def registry(approvals: dict | None = None) -> ToolRegistry:
    reg = ToolRegistry(approvals)
    for name, risk in [("look", "read"), ("draft_it", "draft"), ("save", "write"), ("send_it", "send")]:
        reg.register(tool(name, risk))  # type: ignore[arg-type]
    reg.check_approvals()
    return reg


async def run(reg: ToolRegistry, name: str) -> dict:
    return json.loads(await reg.run(ToolCall(id="c1", name=name), CTX))


async def test_by_default_only_read_tools_are_offered_and_run() -> None:
    reg = registry()

    assert [spec.name for spec in reg.specs()] == ["look"]
    assert await run(reg, "look") == {"ran": "look"}
    for name in ("draft_it", "save", "send_it"):
        assert "needs confirmation" in (await run(reg, name))["error"]


async def test_a_write_tool_set_to_auto_is_offered_and_runs() -> None:
    reg = registry({"save": "auto"})

    assert [spec.name for spec in reg.specs()] == ["look", "save"]
    assert await run(reg, "save") == {"ran": "save"}
    assert "needs confirmation" in (await run(reg, "send_it"))["error"]  # only the named tool changed


async def test_a_read_tool_can_be_made_to_need_confirmation() -> None:
    reg = registry({"look": "confirm"})

    assert reg.specs() == []
    assert "needs confirmation" in (await run(reg, "look"))["error"]


def test_an_approval_for_an_unknown_tool_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="sav"):
        registry({"sav": "auto"})
