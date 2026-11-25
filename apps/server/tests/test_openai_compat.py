"""OpenAI-compatible model handler: request format, response parsing and error classification."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from yyai.core.errors import IntegrationError
from yyai.core.types import ChatMessage, ToolCall, ToolSpec
from yyai.handlers.model.openai_compat import OpenAICompatModel

BASE_URL = "https://model.test/v1"
CHAT_URL = f"{BASE_URL}/chat/completions"


@pytest.fixture
def model() -> OpenAICompatModel:
    return OpenAICompatModel(base_url=BASE_URL, api_key="sk-test")


async def ask(model: OpenAICompatModel, **overrides: Any):
    kwargs: dict[str, Any] = {
        "model": "qwen3.8-27b",
        "messages": [ChatMessage(role="user", content="hi")],
        "tools": [],
        "params": {},
        "timeout_s": 30.0,
    }
    kwargs.update(overrides)
    return await model.chat(**kwargs)


def completion(
    message: dict[str, Any], *, finish_reason: str = "stop", usage: dict[str, Any] | None = None
) -> dict:
    return {
        "id": "chatcmpl-1",
        "choices": [
            {"index": 0, "message": {"role": "assistant", **message}, "finish_reason": finish_reason}
        ],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def tool_call(arguments: Any, *, call_id: str | None = "call_1", name: str = "quote_price") -> dict[str, Any]:
    raw: dict[str, Any] = {"type": "function", "function": {"name": name, "arguments": arguments}}
    if call_id is not None:
        raw["id"] = call_id
    return raw


# --- the request ---------------------------------------------------------------


async def test_request_body_and_headers(model: OpenAICompatModel, mock_http: respx.MockRouter) -> None:
    route = mock_http.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=completion({"content": "ok"}))
    )
    spec = ToolSpec(
        name="quote_price",
        description="Get a price",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    history = [
        ChatMessage(role="system", content="You are helpful"),
        ChatMessage(role="user", content="price?"),
        ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(id="call_9", name="quote_price", arguments={"query": "قهوة"})],
        ),
        ChatMessage(role="tool", content='{"price": 48}', tool_call_id="call_9", name="quote_price"),
    ]
    await ask(model, messages=history, tools=[spec], params={"temperature": 0.3, "max_tokens": 800})

    request = route.calls[0].request
    body = json.loads(request.content)
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert body["model"] == "qwen3.8-27b"
    assert body["temperature"] == 0.3
    assert body["max_tokens"] == 800
    assert body["tool_choice"] == "auto"
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "quote_price",
                "description": "Get a price",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }
    ]
    assert body["messages"][0] == {"role": "system", "content": "You are helpful"}
    assistant = body["messages"][2]
    assert assistant["tool_calls"] == [
        {
            "id": "call_9",
            "type": "function",
            "function": {
                "name": "quote_price",
                "arguments": json.dumps({"query": "قهوة"}, ensure_ascii=False),
            },
        }
    ]
    assert body["messages"][3] == {
        "role": "tool",
        "content": '{"price": 48}',
        "tool_call_id": "call_9",
        "name": "quote_price",
    }


async def test_no_tools_means_no_tools_or_tool_choice_in_the_request(
    model: OpenAICompatModel, mock_http: respx.MockRouter
) -> None:
    route = mock_http.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=completion({"content": "ok"}))
    )
    await ask(model)
    body = json.loads(route.calls[0].request.content)
    assert "tools" not in body
    assert "tool_choice" not in body


async def test_raw_arguments_are_sent_back_exactly_as_the_model_wrote_them(
    model: OpenAICompatModel, mock_http: respx.MockRouter
) -> None:
    route = mock_http.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=completion({"content": "ok"}))
    )
    broken = ToolCall(id="c1", name="quote_price", arguments={}, raw_arguments='{"query": ')
    await ask(model, messages=[ChatMessage(role="assistant", tool_calls=[broken])])
    body = json.loads(route.calls[0].request.content)
    assert body["messages"][0]["tool_calls"][0]["function"]["arguments"] == '{"query": '


async def test_no_api_key_means_no_authorization_header(mock_http: respx.MockRouter) -> None:
    route = mock_http.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=completion({"content": "ok"}))
    )
    await ask(OpenAICompatModel(base_url=BASE_URL))
    assert "Authorization" not in route.calls[0].request.headers


# --- the response ----------------------------------------------------------------


async def test_plain_text_reply(model: OpenAICompatModel, mock_http: respx.MockRouter) -> None:
    mock_http.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=completion({"content": "  أهلاً بك  "}, finish_reason="stop"))
    )
    reply = await ask(model)
    assert reply.text == "أهلاً بك"
    assert reply.tool_calls == []
    assert reply.finish_reason == "stop"
    assert reply.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


async def test_tool_calls_are_parsed_from_json_string_arguments(
    model: OpenAICompatModel, mock_http: respx.MockRouter
) -> None:
    message = {
        "content": None,
        "tool_calls": [
            tool_call('{"query": "قهوة كولومبية", "limit": 3}', call_id="call_a"),
            tool_call("{}", call_id="call_b", name="list_categories"),
        ],
    }
    mock_http.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=completion(message, finish_reason="tool_calls"))
    )
    reply = await ask(model)

    assert reply.text is None
    assert reply.finish_reason == "tool_calls"
    first, second = reply.tool_calls
    assert (first.id, first.name) == ("call_a", "quote_price")
    assert first.arguments == {"query": "قهوة كولومبية", "limit": 3}
    assert first.raw_arguments == '{"query": "قهوة كولومبية", "limit": 3}'
    assert (second.id, second.name, second.arguments) == ("call_b", "list_categories", {})


async def test_invalid_json_arguments_become_empty_dict_and_raw_is_kept(
    model: OpenAICompatModel, mock_http: respx.MockRouter
) -> None:
    broken = '{"query": "coffee", '
    mock_http.post(CHAT_URL).mock(
        return_value=httpx.Response(
            200, json=completion({"content": None, "tool_calls": [tool_call(broken)]})
        )
    )
    (call,) = (await ask(model)).tool_calls
    assert call.arguments == {}
    assert call.raw_arguments == broken


async def test_arguments_that_are_json_but_not_an_object_become_empty_dict(
    model: OpenAICompatModel, mock_http: respx.MockRouter
) -> None:
    mock_http.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=completion({"tool_calls": [tool_call("[1, 2, 3]")]}))
    )
    (call,) = (await ask(model)).tool_calls
    assert call.arguments == {}
    assert call.raw_arguments == "[1, 2, 3]"


async def test_arguments_already_parsed_as_an_object_are_accepted(
    model: OpenAICompatModel, mock_http: respx.MockRouter
) -> None:
    mock_http.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=completion({"tool_calls": [tool_call({"query": "moka"})]}))
    )
    (call,) = (await ask(model)).tool_calls
    assert call.arguments == {"query": "moka"}


async def test_missing_arguments_default_to_empty(
    model: OpenAICompatModel, mock_http: respx.MockRouter
) -> None:
    mock_http.post(CHAT_URL).mock(
        return_value=httpx.Response(
            200, json=completion({"tool_calls": [tool_call(None, name="list_categories")]})
        )
    )
    (call,) = (await ask(model)).tool_calls
    assert call.arguments == {}


async def test_missing_tool_call_id_gets_a_generated_one(
    model: OpenAICompatModel, mock_http: respx.MockRouter
) -> None:
    mock_http.post(CHAT_URL).mock(
        return_value=httpx.Response(
            200,
            json=completion({"tool_calls": [tool_call("{}", call_id=None), tool_call("{}", call_id=None)]}),
        )
    )
    first, second = (await ask(model)).tool_calls
    assert first.id.startswith("call_")
    assert second.id.startswith("call_")
    assert first.id != second.id


async def test_think_block_is_stripped(model: OpenAICompatModel, mock_http: respx.MockRouter) -> None:
    content = "<think>\nThe customer wants the price.\nI should call the tool.\n</think>\n\nالسعر 135 درهم."
    mock_http.post(CHAT_URL).mock(return_value=httpx.Response(200, json=completion({"content": content})))
    assert (await ask(model)).text == "السعر 135 درهم."


async def test_several_think_blocks_are_all_stripped(
    model: OpenAICompatModel, mock_http: respx.MockRouter
) -> None:
    content = "<think>a</think>Hello <think>b</think>there"
    mock_http.post(CHAT_URL).mock(return_value=httpx.Response(200, json=completion({"content": content})))
    assert (await ask(model)).text == "Hello there"


async def test_reply_that_is_only_a_think_block_has_no_text(
    model: OpenAICompatModel, mock_http: respx.MockRouter
) -> None:
    mock_http.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=completion({"content": "<think>hmm</think>"}))
    )
    assert (await ask(model)).text is None


async def test_closing_tag_only_drops_the_reasoning_before_it(
    model: OpenAICompatModel, mock_http: respx.MockRouter
) -> None:
    # Some Qwen chat templates put the opening <think> in the prompt, so only </think> comes back.
    content = "The customer wants the price, so I call the tool.\n</think>\n\nThe price is 48 AED."
    mock_http.post(CHAT_URL).mock(return_value=httpx.Response(200, json=completion({"content": content})))
    assert (await ask(model)).text == "The price is 48 AED."


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("Sure.<think>The customer asks about the price and I should", "Sure."),
        ("<think>still thinking", None),
    ],
)
async def test_unclosed_think_block_never_reaches_the_customer(
    model: OpenAICompatModel, mock_http: respx.MockRouter, content: str, expected: str | None
) -> None:
    # The model ran out of tokens while still thinking: there is no answer, and the reasoning must not leak.
    mock_http.post(CHAT_URL).mock(return_value=httpx.Response(200, json=completion({"content": content})))
    assert (await ask(model)).text == expected


# --- errors ----------------------------------------------------------------------------


@pytest.mark.parametrize("status", [500, 502, 503, 429])
async def test_server_errors_and_rate_limits_are_retryable(
    model: OpenAICompatModel, mock_http: respx.MockRouter, status: int
) -> None:
    mock_http.post(CHAT_URL).mock(return_value=httpx.Response(status, text="upstream trouble"))
    with pytest.raises(IntegrationError) as caught:
        await ask(model)
    assert caught.value.retryable is True
    assert str(status) in str(caught.value)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_client_errors_are_not_retryable(
    model: OpenAICompatModel, mock_http: respx.MockRouter, status: int
) -> None:
    mock_http.post(CHAT_URL).mock(
        return_value=httpx.Response(status, json={"error": {"message": "bad request"}})
    )
    with pytest.raises(IntegrationError) as caught:
        await ask(model)
    assert caught.value.retryable is False


@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
async def test_unreachable_server_is_retryable(
    model: OpenAICompatModel, mock_http: respx.MockRouter, exc: Exception
) -> None:
    mock_http.post(CHAT_URL).mock(side_effect=exc)
    with pytest.raises(IntegrationError) as caught:
        await ask(model)
    assert caught.value.retryable is True


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{}]}, {"error": "model not loaded"}])
async def test_unexpected_response_shape_is_an_integration_error(
    model: OpenAICompatModel, mock_http: respx.MockRouter, body: dict[str, Any]
) -> None:
    mock_http.post(CHAT_URL).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(IntegrationError):
        await ask(model)


async def test_200_with_a_non_json_body_is_an_integration_error(
    model: OpenAICompatModel, mock_http: respx.MockRouter
) -> None:
    # A proxy or captive page in front of the model server can answer 200 with HTML.
    mock_http.post(CHAT_URL).mock(return_value=httpx.Response(200, text="<html>Welcome to the proxy</html>"))
    with pytest.raises(IntegrationError):
        await ask(model)
