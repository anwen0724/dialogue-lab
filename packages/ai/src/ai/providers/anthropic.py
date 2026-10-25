"""Anthropic 供应商组合。"""

from dataclasses import replace

from ai.api.anthropic_messages import AnthropicMessagesAdapter
from ai.auth.api_key import ApiKeyAuth
from ai.provider import create_provider


def create_anthropic_provider(
    *, models=(), base_url="https://api.anthropic.com", client=None, owns_client=False
):
    """认证读取 ANTHROPIC_API_KEY，模型目录由调用者声明。"""
    return create_provider(
        "anthropic",
        models=[replace(model, base_url=model.base_url or base_url) for model in models],
        auth=ApiKeyAuth("ANTHROPIC_API_KEY"),
        adapters={
            "anthropic-messages": AnthropicMessagesAdapter(client, owns_client=owns_client),
        },
    )
