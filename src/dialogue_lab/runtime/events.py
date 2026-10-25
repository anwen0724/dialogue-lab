"""调度器内部命令；网络事件在接入边界编码。"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Submit:
    request_id: UUID
    text: str
    preset: str
    source: str = "text"
