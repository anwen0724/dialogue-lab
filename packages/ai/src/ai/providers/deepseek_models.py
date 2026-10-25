"""DeepSeek 内置目录；每次创建独立的模型描述。

核对日期：2026-10-25。
来源：https://api-docs.deepseek.com/quick_start/pricing/
推理配置：https://api-docs.deepseek.com/guides/thinking_mode/
reasoning_levels 提供 off 和实际思考强度，不重复列出原生别名。
"""

from ai.types.model import Model


def get_builtin_models() -> tuple[Model, ...]:
    """返回两个 API 模型 ID；思考模式不另建模型条目。"""
    return (
        Model(
            provider="deepseek",
            id="deepseek-flash",
            api="openai-completions",
            base_url="",
            name="DeepSeek Flash",
            input_modalities=("text", "image"),
            supports_tools=True,
            reasoning_levels=("off", "low", "high", "max"),
            context_window=1_000_000,
            max_output_tokens=384_000,
        ),
        Model(
            provider="deepseek",
            id="deepseek-v4-pro",
            api="openai-completions",
            base_url="",
            name="DeepSeek V4 Pro",
            input_modalities=("text",),
            supports_tools=True,
            reasoning_levels=("off", "low", "high", "max"),
            context_window=1_000_000,
            max_output_tokens=384_000,
        ),
    )
