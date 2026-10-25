"""所有协议使用同一组增量和终态事件。"""

from dataclasses import dataclass
from typing import Literal

from ai.types.messages import AssistantMessage

type EventType = Literal[
    "start",
    "text_start",
    "text_delta",
    "text_end",
    "thinking_start",
    "thinking_delta",
    "thinking_end",
    "toolcall_start",
    "toolcall_delta",
    "toolcall_end",
    "done",
    "error",
]


@dataclass
class AssistantMessageEvent:
    """partial 是活动消息；保存历史状态时由调用方复制。"""

    type: EventType
    partial: AssistantMessage
    content_index: int | None = None
    delta: str = ""
