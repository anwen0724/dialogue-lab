import json

import httpx
from openai import AsyncOpenAI

from ai.api.openai_responses import OpenAIResponsesAdapter
from ai.auth.api_key import ApiKeyAuth
from ai.models import Models
from ai.provider import create_provider
from ai.types.messages import (
    AssistantMessage,
    Context,
    TextContent,
    ThinkingContent,
    Tool,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from ai.types.model import Model


def events_body(events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)


async def run_responses(events, context=None, options=None):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, text=events_body(events)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        adapter = OpenAIResponsesAdapter(AsyncOpenAI(api_key="test", http_client=http))
        async with Models() as models:
            models.set_provider(
                create_provider("p", auth=ApiKeyAuth(keyless=True), adapters={adapter.id: adapter})
            )
            stream = models.stream_simple(
                Model("p", "m", adapter.id, "https://example.test"),
                context or Context(messages=[UserMessage("hello")]),
                options,
            )
            output = [event async for event in stream]
            result = await stream.result()
    return result, output, requests


async def test_responses_stream_emits_text_and_usage_from_completed_response():
    result, events, requests = await run_responses(
        [
            {"type": "response.created", "response": {"id": "resp-1"}},
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {"type": "message", "id": "msg-1", "role": "assistant", "content": []},
            },
            {
                "type": "response.content_part.added",
                "output_index": 0,
                "content_index": 0,
                "item_id": "msg-1",
                "part": {"type": "output_text", "text": "", "annotations": []},
            },
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "content_index": 0,
                "item_id": "msg-1",
                "delta": "hi",
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-1",
                    "status": "completed",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "total_tokens": 15,
                        "input_tokens_details": {"cached_tokens": 4},
                        "output_tokens_details": {"reasoning_tokens": 2},
                    },
                },
            },
        ]
    )
    assert result.stop_reason == "stop", result.error
    assert result.response_id == "resp-1"
    assert result.content[0].text == "hi"
    assert (result.usage.input, result.usage.output, result.usage.total) == (10, 5, 15)
    assert (result.usage.cache_read, result.usage.reasoning) == (4, 2)
    assert [e.delta for e in events if e.type == "text_delta"] == ["hi"]
    assert requests[0]["input"] == [{"role": "user", "content": "hello"}]
    assert requests[0]["store"] is False


async def test_responses_tool_and_encrypted_reasoning_can_be_replayed():
    reasoning_item = {
        "type": "reasoning",
        "id": "rs-1",
        "summary": [],
        "encrypted_content": "opaque",
    }
    result, events, _ = await run_responses(
        [
            {"type": "response.output_item.added", "output_index": 0, "item": reasoning_item},
            {
                "type": "response.reasoning_summary_text.delta",
                "output_index": 0,
                "summary_index": 0,
                "delta": "plan",
            },
            {"type": "response.output_item.done", "output_index": 0, "item": reasoning_item},
            {
                "type": "response.output_item.added",
                "output_index": 1,
                "item": {
                    "type": "function_call",
                    "id": "fc-1",
                    "call_id": "call-1",
                    "name": "lookup",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.delta",
                "output_index": 1,
                "item_id": "fc-1",
                "delta": '{"n":2}',
            },
            {
                "type": "response.output_item.done",
                "output_index": 1,
                "item": {
                    "type": "function_call",
                    "id": "fc-1",
                    "call_id": "call-1",
                    "name": "lookup",
                    "arguments": '{"n":2}',
                },
            },
            {"type": "response.completed", "response": {"id": "resp-2", "status": "completed"}},
        ]
    )
    assert result.stop_reason == "tool_use", result.error
    assert isinstance(result.content[0], ThinkingContent)
    assert result.content[0].thinking == "plan"
    assert isinstance(result.content[1], ToolCall)
    assert result.content[1].arguments == {"n": 2}
    _, _, replay = await run_responses(
        [
            {"type": "response.completed", "response": {"id": "resp-3", "status": "completed"}},
        ],
        Context(
            messages=[UserMessage("hello"), result, ToolResultMessage("call-1", "lookup", "found")]
        ),
    )
    inputs = replay[0]["input"]
    assert inputs[1] == reasoning_item
    assert inputs[2]["type"] == "function_call" and inputs[2]["call_id"] == "call-1"
    assert inputs[3] == {"type": "function_call_output", "call_id": "call-1", "output": "found"}


async def test_responses_sends_tool_schema_in_responses_format():
    _, _, requests = await run_responses(
        [
            {"type": "response.completed", "response": {"id": "r", "status": "completed"}},
        ],
        Context(tools=[Tool("lookup", "查找", {"type": "object"})]),
    )
    assert requests[0]["tools"] == [
        {
            "type": "function",
            "name": "lookup",
            "description": "查找",
            "parameters": {"type": "object"},
            "strict": False,
        }
    ]


async def test_responses_keeps_distinct_text_blocks_and_rejects_filtered_completion():
    result, events, _ = await run_responses(
        [
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "content_index": 0,
                "item_id": "msg-1",
                "delta": "first",
            },
            {
                "type": "response.output_text.delta",
                "output_index": 1,
                "content_index": 0,
                "item_id": "msg-2",
                "delta": "second",
            },
            {
                "type": "response.incomplete",
                "response": {
                    "id": "r",
                    "status": "incomplete",
                    "incomplete_details": {"reason": "content_filter"},
                },
            },
        ]
    )
    assert result.stop_reason == "error"
    assert [block.text for block in result.content] == ["first", "second"]
    assert result.content[0].metadata["item_id"] == "msg-1"
    assert [e.content_index for e in events if e.type == "text_delta"] == [0, 1]


async def test_responses_text_replay_preserves_item_identity_and_content_parts():
    message = AssistantMessage(
        "p",
        "m",
        "openai-responses",
        [
            TextContent("first", {"item_id": "msg-1", "content_index": 0}),
            TextContent("second", {"item_id": "msg-1", "content_index": 1}),
        ],
    )
    _, _, requests = await run_responses(
        [
            {"type": "response.completed", "response": {"id": "r", "status": "completed"}},
        ],
        Context(messages=[message]),
    )
    assert requests[0]["input"] == [
        {
            "type": "message",
            "role": "assistant",
            "id": "msg-1",
            "content": [
                {"type": "output_text", "text": "first", "annotations": []},
                {"type": "output_text", "text": "second", "annotations": []},
            ],
        }
    ]
