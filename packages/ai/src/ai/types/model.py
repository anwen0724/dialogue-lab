"""模型描述不持有认证信息或运行资源。"""

from dataclasses import dataclass, field
from typing import Literal

type ReasoningLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]


@dataclass(frozen=True)
class ModelDefaults:
    """省略调用参数时采用的模型默认值。"""

    temperature: float | None = None
    max_output_tokens: int | None = None
    reasoning: ReasoningLevel | None = None


@dataclass(frozen=True)
class ModelCost:
    """每百万 token 的可选费率，不表示服务账单。"""

    input: float | None = None
    output: float | None = None
    cache_read: float | None = None
    cache_write: float | None = None


@dataclass(frozen=True)
class Model:
    """一次调用的供应商身份、协议、端点和已声明能力。"""

    provider: str
    id: str
    api: str
    base_url: str
    name: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    input_modalities: tuple[str, ...] = ("text",)
    supports_tools: bool = True
    # 只列出当前模型可选的值；off 表示明确关闭，空目录不接受显式选择。
    reasoning_levels: tuple[ReasoningLevel, ...] = ()
    context_window: int | None = None
    max_output_tokens: int | None = None
    defaults: ModelDefaults = field(default_factory=ModelDefaults)
    compat: object | None = None
    cost: ModelCost | None = None


def resolve_reasoning(model: Model, requested: ReasoningLevel | None) -> ReasoningLevel | None:
    """采用本次选择或模型默认值；不支持的档位明确报错，不改写用户选择。"""
    requested = requested if requested is not None else model.defaults.reasoning
    if requested is None:
        return None
    if requested not in model.reasoning_levels:
        available = ", ".join(model.reasoning_levels) or "no reasoning levels"
        raise ValueError(
            f"Unsupported reasoning level {requested!r} for {model.provider}/{model.id}. "
            f"Available: {available}"
        )
    return requested
