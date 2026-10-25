import json

import httpx
import pytest
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from ai.auth.contracts import AuthContext
from ai.models import Models
from ai.providers.anthropic import create_anthropic_provider
from ai.providers.deepseek import create_deepseek_provider
from ai.providers.openai import create_openai_provider
from ai.types.messages import Context, UserMessage
from ai.types.model import Model, ModelDefaults


@pytest.mark.parametrize(
    "provider_id, factory, api, env, endpoint",
    [
        (
            "openai",
            create_openai_provider,
            "openai-completions",
            "OPENAI_API_KEY",
            "https://api.openai.com/v1/chat/completions",
        ),
        (
            "deepseek",
            create_deepseek_provider,
            "openai-completions",
            "DEEPSEEK_API_KEY",
            "https://api.deepseek.com/chat/completions",
        ),
        (
            "anthropic",
            create_anthropic_provider,
            "anthropic-messages",
            "ANTHROPIC_API_KEY",
            "https://api.anthropic.com/v1/messages",
        ),
    ],
)
async def test_factory_routes_using_its_identity_endpoint_and_environment(
    provider_id, factory, api, env, endpoint
):
    captured = []

    def respond(request):
        captured.append(request)
        if provider_id == "anthropic":
            events = [
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
                {"type": "message_stop"},
            ]
            text = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
        else:
            text = (
                'data: {"id":"r","choices":[{"index":0,"delta":{"content":"ok"},'
                '"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=text)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        cls = AsyncAnthropic if provider_id == "anthropic" else AsyncOpenAI
        client = cls(api_key="wrong", http_client=http)
        provider = factory(
            models=[
                Model(
                    provider_id,
                    "configured-model",
                    api,
                    "",
                    defaults=ModelDefaults(max_output_tokens=100),
                )
            ],
            client=client,
        )
        async with Models(auth_context=AuthContext({env: "configured-key"})) as models:
            models.set_provider(provider, owns_provider=True)
            descriptor = models.get_model(provider_id, "configured-model")
            result = await models.complete_simple(descriptor, Context(messages=[UserMessage("hi")]))
    assert result.stop_reason == "stop", result.error
    assert result.provider == provider_id
    assert str(captured[0].url) == endpoint
    header = "x-api-key" if provider_id == "anthropic" else "authorization"
    assert captured[0].headers[header].endswith("configured-key")
    if provider_id == "deepseek":
        payload = json.loads(captured[0].content)
        assert payload["max_tokens"] == 100
        assert "max_completion_tokens" not in payload
