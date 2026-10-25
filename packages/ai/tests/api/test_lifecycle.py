import asyncio
import json

import httpx
import pytest
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from ai import Context, Model, ModelAuth, ModelDefaults, Models, SimpleOptions
from ai.api.anthropic_messages import AnthropicMessagesAdapter
from ai.api.openai_completions import OpenAICompletionsAdapter
from ai.api.openai_responses import OpenAIResponsesAdapter
from ai.auth.api_key import ApiKeyAuth
from ai.provider import create_provider


@pytest.mark.parametrize(
    "adapter_cls, client_cls, initial",
    [
        (
            OpenAICompletionsAdapter,
            AsyncOpenAI,
            [
                {"id": "r", "choices": [{"index": 0, "delta": {"content": "partial"}}]},
            ],
        ),
        (
            OpenAIResponsesAdapter,
            AsyncOpenAI,
            [
                {
                    "type": "response.output_text.delta",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "partial",
                },
            ],
        ),
        (
            AnthropicMessagesAdapter,
            AsyncAnthropic,
            [
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "partial"},
                },
            ],
        ),
    ],
)
async def test_close_during_event_delivery_releases_the_http_response(
    adapter_cls, client_cls, initial
):
    observing, release = asyncio.Event(), asyncio.Event()

    class Body(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            for item in initial:
                label = f"event: {item['type']}\n" if "type" in item else ""
                yield f"{label}data: {json.dumps(item)}\n\n".encode()
            await release.wait()

        async def aclose(self):
            self.closed = True

    async def observer(event):
        if event.type == "first_text":
            observing.set()
            await release.wait()

    body = Body()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=body,
            )
        )
    ) as http:
        adapter = adapter_cls(client_cls(api_key="test", http_client=http))
        models = Models()
        models.set_provider(
            create_provider("p", auth=ApiKeyAuth(keyless=True), adapters={adapter.id: adapter})
        )
        stream = models.stream_simple(
            Model(
                "p",
                "m",
                adapter.id,
                "https://example.test",
                defaults=ModelDefaults(max_output_tokens=100),
            ),
            Context(),
            SimpleOptions(auth=ModelAuth("test"), observer=observer),
        )
        await asyncio.wait_for(observing.wait(), 2)
        try:
            await asyncio.wait_for(models.aclose(), 2)
            assert (await stream.result()).stop_reason == "aborted"
            assert body.closed
        finally:
            release.set()


@pytest.mark.parametrize(
    "adapter_cls, client_cls, events",
    [
        (
            OpenAICompletionsAdapter,
            AsyncOpenAI,
            [
                {
                    "id": "r",
                    "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}],
                }
            ],
        ),
        (
            AnthropicMessagesAdapter,
            AsyncAnthropic,
            [
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
                {"type": "message_stop"},
            ],
        ),
    ],
)
async def test_keyless_auth_does_not_inherit_injected_sdk_credentials(
    adapter_cls, client_cls, events
):
    captured = []

    def respond(request):
        captured.append(request)
        text = "".join(
            (f"event: {e['type']}\n" if "type" in e else "") + f"data: {json.dumps(e)}\n\n"
            for e in events
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=text)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        adapter = adapter_cls(client_cls(api_key="must-not-leak", http_client=http))
        async with Models() as models:
            models.set_provider(
                create_provider(
                    "local", auth=ApiKeyAuth(keyless=True), adapters={adapter.id: adapter}
                )
            )
            result = await models.complete_simple(
                Model(
                    "local",
                    "m",
                    adapter.id,
                    "https://example.test",
                    defaults=ModelDefaults(max_output_tokens=100),
                ),
                Context(),
            )
    assert result.stop_reason == "stop", result.error
    assert "authorization" not in captured[0].headers
    assert "x-api-key" not in captured[0].headers


@pytest.mark.parametrize(
    "adapter_cls, events",
    [
        (
            OpenAICompletionsAdapter,
            [
                {
                    "id": "r",
                    "choices": [
                        {"index": 0, "delta": {"refusal": "Cannot answer"}, "finish_reason": "stop"}
                    ],
                }
            ],
        ),
        (
            OpenAIResponsesAdapter,
            [
                {
                    "type": "response.refusal.delta",
                    "output_index": 0,
                    "content_index": 0,
                    "item_id": "msg-1",
                    "delta": "Cannot answer",
                },
                {"type": "response.completed", "response": {"id": "r", "status": "completed"}},
            ],
        ),
    ],
)
async def test_provider_refusal_remains_visible_text(adapter_cls, events):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        text = "".join(
            (f"event: {e['type']}\n" if "type" in e else "") + f"data: {json.dumps(e)}\n\n"
            for e in events
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=text)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        adapter = adapter_cls(AsyncOpenAI(api_key="test", http_client=http))
        async with Models() as models:
            models.set_provider(
                create_provider("p", auth=ApiKeyAuth(keyless=True), adapters={adapter.id: adapter})
            )
            result = await models.complete_simple(
                Model("p", "m", adapter.id, "https://example.test"), Context()
            )
            replay = await models.complete_simple(
                Model("p", "m", adapter.id, "https://example.test"), Context(messages=[result])
            )
    assert result.stop_reason == "stop", result.error
    assert result.content[0].text == "Cannot answer"
    assert replay.stop_reason == "stop", replay.error
    if adapter_cls is OpenAICompletionsAdapter:
        assert requests[1]["messages"][0]["refusal"] == "Cannot answer"
    else:
        assert requests[1]["input"][0]["content"] == [
            {"type": "refusal", "refusal": "Cannot answer"}
        ]
