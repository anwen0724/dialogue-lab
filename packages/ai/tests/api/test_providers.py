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
from ai.types.options import SimpleOptions


@pytest.mark.parametrize(
    "factory, expected_ids",
    [
        (create_openai_provider, ["gpt-6.1-sol", "gpt-6-luna", "gpt-6-astra"]),
        (
            create_anthropic_provider,
            ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5", "claude-fable-5-1"],
        ),
        (create_deepseek_provider, ["deepseek-flash", "deepseek-v4-pro"]),
    ],
)
async def test_builtin_catalog_is_available_before_configuring_credentials(
    factory, expected_ids, monkeypatch
):
    for name in ("OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    provider = factory(base_url="https://example.invalid/api")
    try:
        catalog = provider.get_models()
        assert [model.id for model in catalog] == expected_ids
        assert all(model.base_url == "https://example.invalid/api" for model in catalog)
    finally:
        await provider.aclose()


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
@pytest.mark.parametrize("use_builtin", [False, True], ids=["custom", "builtin"])
async def test_factory_routes_using_its_identity_endpoint_and_environment(
    provider_id, factory, api, env, endpoint, use_builtin
):
    captured = []
    model_id = "configured-model"
    if use_builtin:
        model_id = {
            "openai": "gpt-6.1-sol",
            "deepseek": "deepseek-flash",
            "anthropic": "claude-sonnet-5-5",
        }[provider_id]
        if provider_id == "openai":
            endpoint = "https://api.openai.com/v1/responses"

    def respond(request):
        captured.append(request)
        if provider_id == "anthropic":
            events = [
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
                {"type": "message_stop"},
            ]
            text = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
        elif use_builtin and provider_id == "openai":
            text = (
                "event: response.completed\n"
                'data: {"type":"response.completed","response":'
                '{"id":"r","status":"completed","output":[]}}\n\n'
            )
        else:
            text = (
                'data: {"id":"r","choices":[{"index":0,"delta":{"content":"ok"},'
                '"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=text)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        cls = AsyncAnthropic if provider_id == "anthropic" else AsyncOpenAI
        client = cls(api_key="wrong", http_client=http)
        catalog_options = (
            {}
            if use_builtin
            else {
                "models": [
                    Model(
                        provider_id,
                        "configured-model",
                        api,
                        "",
                        defaults=ModelDefaults(max_output_tokens=100),
                    )
                ]
            }
        )
        provider = factory(client=client, **catalog_options)
        async with Models(auth_context=AuthContext({env: "configured-key"})) as models:
            models.set_provider(provider, owns_provider=True)
            descriptor = models.get_model(provider_id, model_id)
            assert descriptor is not None
            options = SimpleOptions(max_output_tokens=100, reasoning="max") if use_builtin else None
            result = await models.complete_simple(
                descriptor, Context(messages=[UserMessage("hi")]), options
            )
    assert result.stop_reason == "stop", result.error
    assert result.provider == provider_id
    assert str(captured[0].url) == endpoint
    header = "x-api-key" if provider_id == "anthropic" else "authorization"
    assert captured[0].headers[header].endswith("configured-key")
    payload = json.loads(captured[0].content)
    assert payload["model"] == model_id
    if use_builtin:
        if provider_id == "openai":
            assert payload["reasoning"] == {"effort": "max"}
        elif provider_id == "anthropic":
            assert payload["thinking"] == {"type": "adaptive"}
            assert payload["output_config"] == {"effort": "max"}
        else:
            assert payload["reasoning_effort"] == "max"
            assert payload["thinking"] == {"type": "enabled"}
    if provider_id == "deepseek":
        assert payload["max_tokens"] == 100
        assert "max_completion_tokens" not in payload
