import json

import httpx
import pytest
from openai import AsyncOpenAI

from ai.api.openai_completions import CompletionsCompat, OpenAICompletionsAdapter
from ai.auth.api_key import ApiKeyAuth
from ai.auth.contracts import ModelAuth
from ai.models import Models
from ai.provider import create_provider
from ai.types.messages import (
    AssistantMessage,
    Context,
    ImageContent,
    SystemMessage,
    TextContent,
    ThinkingContent,
    Tool,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from ai.types.model import Model
from ai.types.options import SimpleOptions


async def invoke_chat(context, *, model=None, options=None):
    """只替换 HTTP 服务边界，真实运行 Models、Provider、适配器和 SDK。"""
    captured = []

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=sse(
                {
                    "id": "r",
                    "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}],
                },
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = AsyncOpenAI(api_key="test", http_client=http)
        provider = create_provider(
            "custom",
            auth=ApiKeyAuth(keyless=True),
            adapters={
                "openai-completions": OpenAICompletionsAdapter(client),
            },
        )
        async with Models() as models:
            models.set_provider(provider)
            model = model or Model("custom", "m", "openai-completions", "https://example.test/v1")
            message = await models.complete_simple(model, context, options)
    return message, captured


def sse(*events):
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"


async def test_real_sdk_request_and_stream_are_normalized():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=sse(
                {
                    "id": "reply",
                    "choices": [{"index": 0, "delta": {"content": "hello"}, "finish_reason": None}],
                },
                {
                    "id": "reply",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 2,
                        "total_tokens": 5,
                        "prompt_tokens_details": {"cached_tokens": 1},
                        "completion_tokens_details": {"reasoning_tokens": 1},
                    },
                },
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = AsyncOpenAI(api_key="test", http_client=http)
        provider = create_provider(
            "custom",
            auth=ApiKeyAuth(keyless=True),
            adapters={
                "openai-completions": OpenAICompletionsAdapter(client),
            },
        )
        async with Models() as models:
            models.set_provider(provider)
            model = Model("custom", "custom-model", "openai-completions", "https://example.test/v1")
            stream = models.stream_simple(model, Context(messages=[UserMessage("hi")]))
            events = [event async for event in stream]
            message = await stream.result()

    assert message.stop_reason == "stop", message.error
    assert message.content[0].text == "hello"
    assert message.usage.total == 5
    assert message.usage.cache_read == 1
    assert message.usage.reasoning == 1
    assert "".join(e.delta for e in events if e.type == "text_delta") == "hello"
    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert str(requests[0].url) == "https://example.test/v1/chat/completions"
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert payload["model"] == "custom-model"
    assert payload["stream"] is True


async def test_history_replay_folds_system_state_and_repairs_missing_tool_result():
    from copy import deepcopy

    context = Context(
        messages=[
            SystemMessage(
                "base",
                sections={"role": "old", "tone": "short"},
                tools_added=[Tool("lookup", "查找", {"type": "object"})],
            ),
            UserMessage([ImageContent("image/png", "base64")]),
            AssistantMessage(
                "other",
                "old",
                "other",
                [
                    ThinkingContent("do not replay", {"signature": "old"}),
                    ToolCall("call-1", "lookup", "{}", {}),
                ],
                stop_reason="tool_use",
            ),
            SystemMessage(sections={"role": "new", "tone": None}),
            ToolResultMessage("call-1", "lookup", "found"),
            AssistantMessage(
                "other",
                "old",
                "other",
                [ToolCall("call-2", "lookup", "{}", {})],
                stop_reason="tool_use",
            ),
            UserMessage("continue"),
            AssistantMessage("other", "old", "other", [TextContent("failed")], stop_reason="error"),
        ]
    )
    before = deepcopy(context)
    result, requests = await invoke_chat(context)
    assert result.stop_reason == "stop", result.error
    messages = requests[0]["messages"]
    assert messages[0]["role"] == "system"
    assert "new" in messages[0]["content"] and "old" not in messages[0]["content"]
    assert "short" not in messages[0]["content"]
    assert messages[1]["content"] == [
        {"type": "text", "text": "(image omitted: model does not support images)"}
    ]
    tool_results = [m for m in messages if m["role"] == "tool"]
    assert tool_results == [
        {"role": "tool", "tool_call_id": "call-1", "content": "found"},
        {"role": "tool", "tool_call_id": "call-2", "content": "No result provided"},
    ]
    assert "do not replay" not in json.dumps(messages)
    assert "failed" not in json.dumps(messages)
    assert requests[0]["tools"][0]["function"]["name"] == "lookup"
    assert context == before


async def test_stream_preserves_thinking_and_incremental_tool_arguments():
    def respond(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=sse(
                {"id": "r", "choices": [{"index": 0, "delta": {"reasoning_content": "plan"}}]},
                {
                    "id": "r",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {"name": "lookup", "arguments": '{"n":'},
                                    }
                                ]
                            },
                        }
                    ],
                },
                {
                    "id": "r",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [{"index": 0, "function": {"arguments": "2}"}}]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                },
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        adapter = OpenAICompletionsAdapter(AsyncOpenAI(api_key="test", http_client=http))
        async with Models() as models:
            models.set_provider(
                create_provider("p", auth=ApiKeyAuth(keyless=True), adapters={adapter.id: adapter})
            )
            stream = models.stream_simple(
                Model("p", "m", adapter.id, "https://example.test"), Context()
            )
            events = [e async for e in stream]
            result = await stream.result()
    assert result.stop_reason == "tool_use", result.error
    assert result.content[0].thinking == "plan"
    call = result.content[1]
    assert call.name == "lookup" and call.id == "call-1"
    assert call.arguments == {"n": 2}
    assert call.arguments_json == '{"n":2}'
    assert [e.delta for e in events if e.type == "toolcall_delta"] == ['{"n":', "2}"]
    assert [e.type for e in events].count("toolcall_end") == 1


async def test_transport_failure_preserves_partial_message_and_incomplete_json():
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            chunk = {
                "id": "r",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "content": "partial",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "c",
                                    "type": "function",
                                    "function": {"name": "tool", "arguments": '{"n":'},
                                }
                            ],
                        },
                    }
                ],
            }
            yield f"data: {json.dumps(chunk)}\n\n".encode()
            raise httpx.ReadError("connection lost")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=BrokenStream(),
            )
        )
    ) as http:
        adapter = OpenAICompletionsAdapter(AsyncOpenAI(api_key="test", http_client=http))
        async with Models() as models:
            models.set_provider(
                create_provider("p", auth=ApiKeyAuth(keyless=True), adapters={adapter.id: adapter})
            )
            stream = models.stream_simple(
                Model("p", "m", adapter.id, "https://example.test"), Context()
            )
            events = [e async for e in stream]
            result = await stream.result()
    assert result.stop_reason == "error"
    assert result.content[0].text == "partial"
    assert result.content[1].arguments_json == '{"n":'
    assert result.content[1].arguments is None
    assert result.content[1].arguments_error
    assert events[-1].type == "error"


async def test_simple_options_use_declared_reasoning_mapping_and_hard_tool_constraints():
    model = Model(
        "custom",
        "reasoner",
        "openai-completions",
        "https://example.test",
        reasoning_levels=("low", "high"),
        compat=CompletionsCompat(),
    )
    result, requests = await invoke_chat(
        Context(messages=[UserMessage("hi")]),
        model=model,
        options=SimpleOptions(temperature=0.2, max_output_tokens=100, reasoning="xhigh"),
    )
    assert result.stop_reason == "stop", result.error
    assert requests[0]["reasoning_effort"] == "high"
    assert requests[0]["max_completion_tokens"] == 100
    assert requests[0]["temperature"] == 0.2

    no_strict = Model(
        "custom",
        "m",
        "openai-completions",
        "https://example.test",
        compat=CompletionsCompat(strict_tools=False),
    )
    required = Tool("t", "t", {"type": "object"}, constraint_mode="require")
    failed, requests = await invoke_chat(Context(tools=[required]), model=no_strict)
    assert failed.stop_reason == "error"
    assert requests == []


async def test_request_hooks_change_request_while_diagnostics_are_read_only_and_isolated():
    captured, native, diagnostics = [], [], []

    def respond(request):
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream", "x-test": "response"},
            text=sse(
                {
                    "id": "r",
                    "choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": "stop"}],
                },
            ),
        )

    def observer(event):
        diagnostics.append(event)
        raise RuntimeError("diagnostic failure")

    def headers(values):
        assert values["x-source"] == "request"
        return {**values, "x-hook": "yes"}

    responses = []
    options = SimpleOptions(
        auth=ModelAuth("explicit", {"X-Source": "auth"}),
        headers={"X-SOURCE": "request"},
        transform_headers=headers,
        on_payload=lambda body: {**body, "seed": 7, "custom_field": True},
        on_response=responses.append,
        on_provider_stream_event=native.append,
        observer=observer,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        adapter = OpenAICompletionsAdapter(AsyncOpenAI(api_key="wrong", http_client=http))
        async with Models() as models:
            models.set_provider(
                create_provider("p", auth=ApiKeyAuth(keyless=True), adapters={adapter.id: adapter})
            )
            result = await models.complete_simple(
                Model("p", "m", adapter.id, "https://example.test", headers={"x-source": "model"}),
                Context(),
                options,
            )
    assert result.stop_reason == "stop", result.error
    assert captured[0].headers["authorization"] == "Bearer explicit"
    assert captured[0].headers["x-hook"] == "yes"
    assert json.loads(captured[0].content)["seed"] == 7
    assert json.loads(captured[0].content)["custom_field"] is True
    assert responses[0].status == 200
    assert native[0]["id"] == "r"
    kinds = [d.type for d in diagnostics]
    assert kinds == ["start", "first_event", "first_text", "end"]
    assert diagnostics[2].elapsed >= diagnostics[1].elapsed >= 0


@pytest.mark.parametrize(
    "code, expected_requests, expected_reason",
    [
        ("rate_limit_exceeded", 2, "stop"),
        ("insufficient_quota", 1, "error"),
    ],
)
async def test_request_retries_distinguish_transient_limit_from_quota(
    code, expected_requests, expected_reason
):
    requests = []
    responses = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429,
                headers={"retry-after": "0"},
                json={
                    "error": {
                        "message": "limited",
                        "code": code,
                    }
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=sse(
                {
                    "id": "r",
                    "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}],
                },
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        adapter = OpenAICompletionsAdapter(AsyncOpenAI(api_key="test", http_client=http))
        async with Models() as models:
            models.set_provider(
                create_provider("p", auth=ApiKeyAuth(keyless=True), adapters={adapter.id: adapter})
            )
            result = await models.complete_simple(
                Model("p", "m", adapter.id, "https://example.test"),
                Context(),
                SimpleOptions(max_retries=1, timeout=3, on_response=responses.append),
            )
    assert result.stop_reason == expected_reason
    assert len(requests) == expected_requests
    assert requests[0].extensions["timeout"]["read"] == 3
    assert [response.status for response in responses] == (
        [429, 200] if expected_requests == 2 else [429]
    )


async def test_same_model_thinking_and_tool_images_are_not_lost_in_replay():
    previous = AssistantMessage(
        "custom",
        "m",
        "openai-completions",
        [
            ThinkingContent("plan"),
            ToolCall("call-1", "lookup", "{}", {}),
        ],
        stop_reason="tool_use",
    )
    model = Model(
        "custom",
        "m",
        "openai-completions",
        "https://example.test",
        input_modalities=("text", "image"),
    )
    result, requests = await invoke_chat(
        Context(
            messages=[
                previous,
                ToolResultMessage(
                    "call-1", "lookup", [TextContent("found"), ImageContent("image/png", "abcd")]
                ),
            ]
        ),
        model=model,
    )
    assert result.stop_reason == "stop", result.error
    messages = requests[0]["messages"]
    assert messages[0]["reasoning_content"] == "plan"
    assert messages[1] == {"role": "tool", "tool_call_id": "call-1", "content": "found"}
    assert messages[2]["role"] == "user"
    assert messages[2]["content"][-1]["image_url"]["url"] == "data:image/png;base64,abcd"


async def test_cross_protocol_tool_ids_remain_paired_after_normalization():
    import re

    identifier = "call|" + "x" * 100
    source = AssistantMessage(
        "other", "other", "other", [ToolCall(identifier, "t", "{}", {})], stop_reason="tool_use"
    )
    result, requests = await invoke_chat(
        Context(messages=[source, ToolResultMessage(identifier, "t", "ok")])
    )
    assert result.stop_reason == "stop", result.error
    call_id = requests[0]["messages"][0]["tool_calls"][0]["id"]
    assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", call_id)
    assert requests[0]["messages"][1]["tool_call_id"] == call_id
    assert source.content[0].id == identifier
