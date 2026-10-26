"""应用摘要保留独立身份；只在模型输入转换时使用 user 角色。"""

from dataclasses import dataclass

from ai import UserMessage
from ai.types.messages import Message


@dataclass(frozen=True)
class CompactionSummary:
    summary: str


type ApplicationMessage = Message | CompactionSummary


def convert_to_llm(messages: list[ApplicationMessage]) -> list[Message]:
    """按 pi 的摘要包装转换，不修改应用消息或数据库。"""
    return [
        UserMessage(
            "The conversation history before this point was compacted "
            "into the following summary:"
            f"\n\n<summary>\n{message.summary}\n</summary>"
        )
        if isinstance(message, CompactionSummary)
        else message
        for message in messages
    ]
