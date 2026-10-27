"""一轮回复使用的配置，开始后不随全局设置变化。"""

from collections.abc import Callable
from dataclasses import dataclass

from ai import Model, SimpleOptions


@dataclass(frozen=True)
class ReplySettings:
    model: Model
    options: SimpleOptions
    synthesis_factory: Callable | None
    speech_notice: str | None = None
