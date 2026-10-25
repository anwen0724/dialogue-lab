"""通过公开调用入口验证模型选项和实际发送的协议字段。"""

import json

import httpx
import pytest
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from ai import Context, Models, SimpleOptions, UserMessage
from ai.auth.contracts import ModelAuth
from ai.providers.anthropic import create_anthropic_provider
from ai.providers.deepseek import create_deepseek_provider
from ai.providers.openai import create_openai_provider


async def call_builtin(factory, provider_id, model_id, options):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        if request.url.path.endswith("/responses"):
            events = [
                {
                    "type": "response.completed",
                    "response": {
                        "id": "r",
                        "status": "completed",
                        "output": [],
                    },
                }
            ]
        elif request.url.path.endswith("/messages"):
            events = [
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
                {"type": "message_stop"},
            ]
        else:
            events = [
                {
                    "id": "r",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                }
            ]
        text = "".join(
            (f"event: {event['type']}\n" if "type" in event else "")
            + f"data: {json.dumps(event)}\n\n"
            for event in events
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=text)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        sdk = AsyncAnthropic if provider_id == "anthropic" else AsyncOpenAI
        client = sdk(api_key="test", http_client=http)
        async with Models() as models:
            models.set_provider(factory(client=client), owns_provider=True)
            model = models.get_model(provider_id, model_id)
            assert model is not None
            result = await models.complete_simple(
                model,
                Context(messages=[UserMessage("hi")]),
                options,
            )
    return result, requests


@pytest.mark.parametrize(
    "factory, provider_id, model_id, expected",
    [
        (create_openai_provider, "openai", "gpt-6-luna", {"reasoning": {"effort": "none"}}),
        (
            create_deepseek_provider,
            "deepseek",
            "deepseek-flash",
            {"thinking": {"type": "disabled"}},
        ),
        (
            create_anthropic_provider,
            "anthropic",
            "claude-haiku-5-5",
            {"thinking": {"type": "disabled"}},
        ),
    ],
)
@pytest.mark.parametrize("selection", [None, "off"], ids=["default", "off"])
async def test_off_is_explicit_and_omission_preserves_provider_default(
    factory,
    provider_id,
    model_id,
    expected,
    selection,
):
    result, requests = await call_builtin(
        factory,
        provider_id,
        model_id,
        SimpleOptions(auth=ModelAuth("test"), max_output_tokens=4096, reasoning=selection),
    )
    assert result.stop_reason == "stop", result.error
    controls = {
        key: value
        for key, value in requests[0].items()
        if key in ("reasoning", "reasoning_effort", "thinking", "output_config")
    }
    assert controls == (expected if selection == "off" else {})


@pytest.mark.parametrize(
    "factory, provider_id, model_id",
    [
        (create_openai_provider, "openai", "gpt-6.1-sol"),
        (create_anthropic_provider, "anthropic", "claude-sonnet-5-5"),
    ],
)
async def test_off_is_rejected_when_model_cannot_disable_thinking(factory, provider_id, model_id):
    result, requests = await call_builtin(
        factory,
        provider_id,
        model_id,
        SimpleOptions(auth=ModelAuth("test"), max_output_tokens=4096, reasoning="off"),
    )
    assert result.stop_reason == "error"
    assert "off" in result.error.message
    assert requests == []
