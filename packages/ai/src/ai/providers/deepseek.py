"""DeepSeek 供应商复用 Completions 协议，保留独立身份和认证。"""

from dataclasses import replace

from ai.api.openai_completions import CompletionsCompat, OpenAICompletionsAdapter
from ai.auth.api_key import ApiKeyAuth
from ai.provider import create_provider
from ai.providers.deepseek_models import get_builtin_models


def create_deepseek_provider(
    *, models=None, base_url="https://api.deepseek.com", client=None, owns_client=False
):
    """省略目录时使用内置模型；显式目录替换内置项，兼容配置保持可覆盖。"""
    models = get_builtin_models() if models is None else models
    compat = CompletionsCompat(
        max_tokens_field="max_tokens", strict_tools=False, thinking_format="deepseek"
    )
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
