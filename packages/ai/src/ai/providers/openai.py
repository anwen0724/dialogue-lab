"""OpenAI 供应商组合。"""

from dataclasses import replace

from ai.api.openai_completions import OpenAICompletionsAdapter
from ai.api.openai_responses import OpenAIResponsesAdapter
from ai.auth.api_key import ApiKeyAuth
from ai.provider import create_provider


def create_openai_provider(
    *, models=(), base_url="https://api.openai.com/v1", client=None, owns_client=False
):
    """目录由宿主声明，不选择默认模型；空端点在构造时补齐。"""
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
