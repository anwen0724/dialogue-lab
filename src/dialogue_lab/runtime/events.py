"""调度器内部命令；网络事件在接入边界编码。"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Submit:
    request_id: UUID
    text: str
    preset: str
    source: str = "text"
    input_epoch: int | None = None


OPENING_REQUEST = (
    "现在开始一段新对话。请按照你的身份和当前情境，"
    "主动向我打招呼，并用一个容易回答的问题开启交流。直接说出开场内容。"
)
