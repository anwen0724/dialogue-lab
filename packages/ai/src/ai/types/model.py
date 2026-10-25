"""模型描述不持有认证信息或运行资源。"""

from dataclasses import dataclass, field
from typing import Literal

type ReasoningLevel = Literal["minimal", "low", "medium", "high", "xhigh"]


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
    reasoning_levels: tuple[ReasoningLevel, ...] = ()
    context_window: int | None = None
    max_output_tokens: int | None = None
    defaults: ModelDefaults = field(default_factory=ModelDefaults)
    compat: object | None = None
    cost: ModelCost | None = None


def map_reasoning(model: Model, requested: ReasoningLevel | None) -> ReasoningLevel | None:
    """通用级别向下钳制到已声明等级；无推理能力时忽略通用推理选项。"""
    levels = ("minimal", "low", "medium", "high", "xhigh")
    requested = requested if requested is not None else model.defaults.reasoning
    if requested is None:
        return None
    if requested not in levels:
        raise ValueError(f"Unknown reasoning level: {requested}")
    if not model.reasoning_levels:
        return None
    supported = [level for level in levels if level in model.reasoning_levels]
    allowed = [level for level in supported if levels.index(level) <= levels.index(requested)]
    return allowed[-1] if allowed else supported[0]
