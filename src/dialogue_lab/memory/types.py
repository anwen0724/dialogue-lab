"""长期记忆及其提供给上下文的摘录。"""

from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryExcerpt:
    id: int
    content: str
    revision: int
    source_message_ids: list[int]


def redact_message(row):
    """模型投影撤回受影响轮次；保留角色、调用标识和原始存储。"""
    row = dict(row)
    payload = deepcopy(row["message_json"])
    notice = "此轮包含已纠正或撤回的记忆，旧内容不再提供；需要时询问用户。"
    if row["message_kind"] == "user_message":
        payload["model_content"] = [{"type": "text", "text": notice}]
        payload["display_content"] = [{"type": "text", "text": notice}]
    elif row["message_kind"] == "tool_result":
        payload["content"] = notice
        payload["is_error"] = True
    else:
        calls = [block for block in payload["content"] if block["type"] == "tool_call"]
        for call in calls:
            call["arguments"] = {}
            call["arguments_json"] = "{}"
        payload["content"] = [{"type": "text", "text": notice}, *calls]
        payload["usage"] = {}
    payload.pop("memory_refs", None)
    row["message_json"] = payload
    return row
