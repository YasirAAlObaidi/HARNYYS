"""Model handler for any OpenAI-compatible server.

Covers TensorFold, vLLM, SGLang, llama.cpp, Ollama, LM Studio and hosted APIs
that speak the same format. Converts their responses into our ModelReply.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from yyai.core.errors import IntegrationError
from yyai.core.types import ChatMessage, ModelReply, ToolCall, ToolSpec
from yyai.handlers.common.http import make_client, raise_for_status

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


class OpenAICompatModel:
    def __init__(self, *, base_url: str, api_key: str | None = None, client: httpx.AsyncClient | None = None):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or make_client(base_url=base_url.rstrip("/"), headers=headers, timeout_s=180)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        *,
        model: str,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        params: Mapping[str, Any],
        timeout_s: float,
    ) -> ModelReply:
        payload: dict[str, Any] = {"model": model, "messages": [_to_wire(m) for m in messages], **params}
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]
            payload["tool_choice"] = "auto"
        try:
            response = await self._client.post("/chat/completions", json=payload, timeout=timeout_s)
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Model server unreachable: {exc}", retryable=True) from exc
        raise_for_status(response, "Model request")
        try:
            body = response.json()
        except ValueError as exc:  # e.g. a proxy answering 200 with an HTML page
            raise IntegrationError(f"Model server sent a response that is not JSON: {response.text[:200]}") from exc
        return _from_wire(body)


def _to_wire(message: ChatMessage) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": call.raw_arguments or json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    if message.tool_call_id:
        wire["tool_call_id"] = message.tool_call_id
    if message.name and message.role == "tool":
        wire["name"] = message.name
    return wire


def _strip_reasoning(text: str) -> str:
    """Remove the model's reasoning so that it never reaches the customer.

    Handles <think>...</think> blocks, a lone </think> (some Qwen chat templates put the opening tag in the
    prompt, so only the closing one comes back: the answer is what follows it) and an unclosed <think>
    (the model ran out of tokens while thinking: everything from the tag on is reasoning).
    """
    text = _THINK_BLOCK.sub("", text)
    if _THINK_CLOSE in text:
        text = text.rsplit(_THINK_CLOSE, 1)[1]
    if _THINK_OPEN in text:
        text = text.split(_THINK_OPEN, 1)[0]
    return text.strip()


def _from_wire(body: dict[str, Any]) -> ModelReply:
    try:
        choice = body["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise IntegrationError(f"Unexpected model response shape: {str(body)[:300]}") from exc

    text = message.get("content")
    if isinstance(text, str):
        text = _strip_reasoning(text) or None

    calls: list[ToolCall] = []
    for raw in message.get("tool_calls") or []:
        function = raw.get("function") or {}
        raw_args = function.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            if not isinstance(args, dict):
                args = {}
        except json.JSONDecodeError:
            args = {}
        calls.append(
            ToolCall(
                id=raw.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                name=function.get("name") or "",
                arguments=args,
                raw_arguments=raw_args if isinstance(raw_args, str) else json.dumps(raw_args),
            )
        )
    return ModelReply(
        text=text,
        tool_calls=calls,
        finish_reason=choice.get("finish_reason"),
        usage=body.get("usage") or {},
    )
