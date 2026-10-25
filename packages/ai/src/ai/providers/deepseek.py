"""DeepSeek 供应商复用 Completions 协议，保留独立身份和认证。"""

from dataclasses import replace

from ai.api.openai_completions import CompletionsCompat, OpenAICompletionsAdapter
from ai.auth.api_key import ApiKeyAuth
from ai.provider import create_provider


def create_deepseek_provider(
    *, models=(), base_url="https://api.deepseek.com", client=None, owns_client=False
):
    """max_tokens 与 strict 支持由兼容配置声明，不在协议内判断名称。"""
    compat = CompletionsCompat(max_tokens_field="max_tokens", strict_tools=False)
    return create_provider(
        "deepseek",
        models=[
            replace(model, base_url=model.base_url or base_url, compat=model.compat or compat)
            for model in models
        ],
        auth=ApiKeyAuth("DEEPSEEK_API_KEY"),
        adapters={
            "openai-completions": OpenAICompletionsAdapter(client, owns_client=owns_client),
        },
    )
