"""Anthropic 内置目录；每次创建独立的模型描述。

核对日期：2026-10-25。
来源：https://platform.claude.com/docs/en/models/overview
推理配置：https://platform.claude.com/docs/en/build-with-claude/effort
reasoning_levels 声明实际可选的思考强度；只有支持关闭的模型提供 off。
"""

from ai.api.anthropic_messages import AnthropicCompat
from ai.types.model import Model


def get_builtin_models() -> tuple[Model, ...]:
    """新型号使用自适应推理，不使用旧型号的 thinking budget 映射。"""
    return tuple(
        Model(
            provider="anthropic",
            id=model_id,
            api="anthropic-messages",
            base_url="",
            name=name,
            input_modalities=("text", "image"),
            supports_tools=True,
            reasoning_levels=(("off",) if can_disable else ())
            + ("low", "medium", "high", "xhigh", "max"),
            context_window=1_000_000,
            max_output_tokens=128_000,
            compat=AnthropicCompat(adaptive_thinking=True),
        )
        # Sonnet 的 between_tools 仍允许工具间思考，不能标成完全关闭。
        for model_id, name, can_disable in (
            ("claude-sonnet-5-5", "Claude Sonnet 5.5", False),
            ("claude-haiku-5-5", "Claude Haiku 5.5", True),
            ("claude-opus-5-5", "Claude Opus 5.5", False),
            ("claude-fable-5-1", "Claude Fable 5.1", False),
        )
    )
