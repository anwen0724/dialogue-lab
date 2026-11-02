"""一次上下文构建的材料与诊断记录。"""

from dataclasses import dataclass, field

from ai import Tool

from dialogue_lab.context.messages import ApplicationMessage
from dialogue_lab.memory.types import MemoryExcerpt
from dialogue_lab.sessions.types import SessionState


@dataclass
class PreparedContext:
    """内部准备结果，分别保存指令正文、应用消息和压缩定位信息。"""

    system_prompt: str
    messages: list[ApplicationMessage]
    entry_ids: list[int]
    anchor_entry_id: int | None
    cache_key: str
    tokens: int
    tools: list[Tool] = field(default_factory=list)
    session_state: SessionState = field(default_factory=SessionState)
    memories: list[MemoryExcerpt] = field(default_factory=list)
    report: dict = field(default_factory=dict)
    memory_revision: int = 0
    memory_refs: dict[str, int] = field(default_factory=dict)
