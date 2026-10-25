"""Anthropic 供应商组合。"""

from dataclasses import replace

from ai.api.anthropic_messages import AnthropicMessagesAdapter
from ai.auth.api_key import ApiKeyAuth
from ai.provider import create_provider
from ai.providers.anthropic_models import get_builtin_models


def create_anthropic_provider(
    *, models=None, base_url="https://api.anthropic.com", client=None, owns_client=False
):
    """省略目录时使用内置模型；显式目录替换内置项，认证读取 ANTHROPIC_API_KEY。"""
    models = get_builtin_models() if models is None else models
    return create_provider(
        "anthropic",
        models=[replace(model, base_url=model.base_url or base_url) for model in models],
        auth=ApiKeyAuth("ANTHROPIC_API_KEY"),
        adapters={
            "anthropic-messages": AnthropicMessagesAdapter(client, owns_client=owns_client),
        },
    )
