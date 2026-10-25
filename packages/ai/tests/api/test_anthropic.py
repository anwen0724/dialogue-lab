import json

import httpx
from anthropic import AsyncAnthropic

from ai.api.anthropic_messages import AnthropicMessagesAdapter, AnthropicOptions
from ai.auth.api_key import ApiKeyAuth
from ai.auth.contracts import ModelAuth
from ai.models import Models
from ai.provider import create_provider
from ai.types.messages import Context, SystemMessage, Tool, ToolResultMessage, UserMessage
from ai.types.model import Model, ModelDefaults
from ai.types.options import SimpleOptions


async def run_anthropic(events, context=None, options=None, *, model=None):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        text = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=text)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        adapter = AnthropicMessagesAdapter(AsyncAnthropic(api_key="test", http_client=http))
        async with Models() as models:
            models.set_provider(
                create_provider("p", auth=ApiKeyAuth(keyless=True), adapters={adapter.id: adapter})
            )
            model = model or Model(
                "p",
                "m",
                adapter.id,
                "https://example.test",
                defaults=ModelDefaults(max_output_tokens=100),
            )
            method = (
                models.stream if isinstance(options, AnthropicOptions) else models.stream_simple
            )
            stream = method(
                model,
                context or Context(messages=[UserMessage("hello")]),
                options or SimpleOptions(auth=ModelAuth("test")),
            )
            output = [event async for event in stream]
            result = await stream.result()
    return result, output, requests


async def test_simple_reasoning_does_not_invent_a_budget_for_budget_based_models():
    model = Model(
        "p",
        "budget-model",
        "anthropic-messages",
        "https://example.test",
        reasoning_levels=("high",),
        max_output_tokens=4096,
    )
    result, _, requests = await run_anthropic(
        [
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            {"type": "message_stop"},
        ],
        options=SimpleOptions(reasoning="high"),
        model=model,
    )
    assert result.stop_reason == "error"
    assert "thinking_budget" in result.error.message
    assert requests == []


async def test_anthropic_stream_text_and_cache_usage_are_normalized():
    result, events, requests = await run_anthropic(
        [
            {
                "type": "message_start",
                "message": {
                    "id": "msg-1",
                    "type": "message",
                    "role": "assistant",
                    "model": "m",
                    "content": [],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 0,
                        "cache_read_input_tokens": 4,
                        "cache_creation_input_tokens": 3,
                    },
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "hi"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 2},
            },
            {"type": "message_stop"},
        ]
    )
    assert result.stop_reason == "stop", result.error
    assert result.response_id == "msg-1"
    assert result.content[0].text == "hi"
    # Anthropic input_tokens 不含缓存读写，统一 input 包含已知输入总量。
    assert (result.usage.input, result.usage.output, result.usage.total) == (17, 2, 19)
    assert (result.usage.cache_read, result.usage.cache_write) == (4, 3)
    assert requests[0]["max_tokens"] == 100
    assert requests[0]["messages"] == [{"role": "user", "content": "hello"}]


async def test_signed_thinking_and_tool_reply_replay_without_executing_tool():
    result, events, _ = await run_anthropic(
        [
            {
                "type": "message_start",
                "message": {
                    "id": "m1",
                    "type": "message",
                    "role": "assistant",
                    "model": "m",
                    "content": [],
                    "usage": {"input_tokens": 1, "output_tokens": 0},
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": "", "signature": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "plan"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "signed"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "lookup",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '{"n":2}'},
            },
            {"type": "content_block_stop", "index": 1},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 5},
            },
            {"type": "message_stop"},
        ]
    )
    assert result.stop_reason == "tool_use", result.error
    assert result.content[0].thinking == "plan"
    assert result.content[0].metadata["signature"] == "signed"
    assert result.content[1].arguments == {"n": 2}
    _, _, requests = await run_anthropic(
        [
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            {"type": "message_stop"},
        ],
        Context(
            messages=[
                SystemMessage("system"),
                UserMessage("question"),
                result,
                ToolResultMessage("tool-1", "lookup", "found"),
            ],
            tools=[Tool("lookup", "查找", {"type": "object"})],
        ),
    )
    assert requests[0]["system"] == "system"
    assert requests[0]["tools"][0]["input_schema"] == {"type": "object"}
    assistant = requests[0]["messages"][1]["content"]
    assert assistant[0] == {"type": "thinking", "thinking": "plan", "signature": "signed"}
    assert assistant[1] == {"type": "tool_use", "id": "tool-1", "name": "lookup", "input": {"n": 2}}
    assert requests[0]["messages"][2]["content"][0]["tool_use_id"] == "tool-1"


async def test_anthropic_explicit_thinking_budget_and_cache_control():
    _, _, requests = await run_anthropic(
        [
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            {"type": "message_stop"},
        ],
        Context(system_prompt="system", messages=[UserMessage("hello")]),
        AnthropicOptions(
            auth=ModelAuth("test"), max_tokens=2048, thinking_budget=1024, cache_system=True
        ),
    )
    assert requests[0]["thinking"] == {"type": "enabled", "budget_tokens": 1024}
    assert requests[0]["system"] == [
        {"type": "text", "text": "system", "cache_control": {"type": "ephemeral"}}
    ]


async def test_required_tool_constraints_fail_before_request_when_not_supported():
    result, _, requests = await run_anthropic(
        [
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            {"type": "message_stop"},
        ],
        Context(tools=[Tool("t", "t", {"type": "object"}, constraint_mode="require")]),
    )
    assert result.stop_reason == "error"
    assert requests == []


async def test_error_tool_images_follow_all_tool_results_outside_error_blocks():
    from ai.types.messages import AssistantMessage, ImageContent, TextContent, ToolCall

    # 声明 image 能力后，错误工具结果中的图片应保留，但不嵌入 is_error 块。
    context = Context(
        messages=[
            AssistantMessage(
                "p",
                "m",
                "anthropic-messages",
                [
                    ToolCall("one", "lookup", "{}", {}),
                    ToolCall("two", "lookup", "{}", {}),
                ],
                stop_reason="tool_use",
            ),
            ToolResultMessage(
                "one",
                "lookup",
                [TextContent("failed"), ImageContent("image/png", "abcd")],
                is_error=True,
            ),
            ToolResultMessage("two", "lookup", "found"),
        ]
    )
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                "event: message_delta\ndata: "
                '{"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n\n'
                'event: message_stop\ndata: {"type":"message_stop"}\n\n'
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        adapter = AnthropicMessagesAdapter(AsyncAnthropic(api_key="test", http_client=http))
        async with Models() as models:
            models.set_provider(
                create_provider("p", auth=ApiKeyAuth(keyless=True), adapters={adapter.id: adapter})
            )
            result = await models.complete_simple(
                Model(
                    "p",
                    "m",
                    adapter.id,
                    "https://example.test",
                    input_modalities=("text", "image"),
                    defaults=ModelDefaults(max_output_tokens=100),
                ),
                context,
                SimpleOptions(auth=ModelAuth("test")),
            )
    assert result.stop_reason == "stop", result.error
    content = requests[0]["messages"][1]["content"]
    assert [b["type"] for b in content][:2] == ["tool_result", "tool_result"]
    assert all(b["type"] != "image" for b in content[0]["content"])
    assert content[-1]["type"] == "image" and content[-1]["source"]["data"] == "abcd"
