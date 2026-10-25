"""真实调用单独显式启用；离线测试不读取或验证真实凭据。"""

import os

import pytest

from ai import Context, Model, Models, SimpleOptions, UserMessage

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("AI_LIVE") != "1", reason="Set AI_LIVE=1 to enable real calls"),
]


async def test_explicit_live_model_stream():
    provider_id = os.environ["AI_LIVE_PROVIDER"]
    model_id = os.environ["AI_LIVE_MODEL"]
    api = os.environ["AI_LIVE_API"]
    if provider_id == "openai":
        from ai.providers.openai import create_openai_provider as factory
    elif provider_id == "anthropic":
        from ai.providers.anthropic import create_anthropic_provider as factory
    elif provider_id == "deepseek":
        from ai.providers.deepseek import create_deepseek_provider as factory
    else:
        raise ValueError("AI_LIVE_PROVIDER must be openai, anthropic, or deepseek")
    provider = factory(models=[Model(provider_id, model_id, api, "")])
    async with Models() as models:
        models.set_provider(provider, owns_provider=True)
        model = models.get_model(provider_id, model_id)
        stream = models.stream_simple(
            model,
            Context(messages=[UserMessage("Say hello briefly.")]),
            SimpleOptions(max_output_tokens=256),
        )
        events = [event async for event in stream]
        result = await stream.result()
    assert result.stop_reason in ("stop", "length"), result.error
    assert any(event.type == "text_delta" and event.delta for event in events)
