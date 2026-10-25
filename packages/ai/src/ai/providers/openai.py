"""OpenAI 供应商组合。"""

from dataclasses import replace

from ai.api.openai_completions import OpenAICompletionsAdapter
from ai.api.openai_responses import OpenAIResponsesAdapter
from ai.auth.api_key import ApiKeyAuth
from ai.provider import create_provider
from ai.providers.openai_models import get_builtin_models


def create_openai_provider(
    *, models=None, base_url="https://api.openai.com/v1", client=None, owns_client=False
):
    """省略目录时使用内置模型；显式目录替换内置项，空端点在构造时补齐。"""
    models = get_builtin_models() if models is None else models
    return create_provider(
        "openai",
        models=[replace(model, base_url=model.base_url or base_url) for model in models],
        auth=ApiKeyAuth("OPENAI_API_KEY"),
        adapters={
            "openai-completions": OpenAICompletionsAdapter(client, owns_client=owns_client),
            # 同一个外部客户端只由第一个适配器承担显式关闭责任。
            "openai-responses": OpenAIResponsesAdapter(client, owns_client=False),
        },
    )
