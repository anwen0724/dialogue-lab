"""OpenAI 内置目录；每次创建独立的模型描述。

核对日期：2026-10-25。
来源：https://developers.openai.com/api/docs/models
reasoning_levels 声明实际可选的思考强度；只有支持关闭的模型提供 off。
"""

from ai.types.model import Model


def get_builtin_models() -> tuple[Model, ...]:
    """返回 Responses 模型目录；端点由供应商创建函数填入。"""
    return tuple(
        Model(
            provider="openai",
            id=model_id,
            api="openai-responses",
            base_url="",
            name=name,
            input_modalities=("text", "image"),
            supports_tools=True,
            reasoning_levels=(("off",) if can_disable else ())
            + ("low", "medium", "high", "xhigh", "max"),
            context_window=1_050_000,
            max_output_tokens=128_000,
        )
        for model_id, name, can_disable in (
            ("gpt-6.1-sol", "GPT-6.1 Sol", False),
            ("gpt-6-luna", "GPT-6 Luna", True),
            ("gpt-6-astra", "GPT-6 Astra", False),
        )
    )
