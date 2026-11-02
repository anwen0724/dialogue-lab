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
    """模型投影撤回失效消息；保留角色、调用标识和原始存储。"""
    row = dict(row)
    payload = deepcopy(row["message_json"])
    notice = "此消息包含已纠正或撤回的记忆，旧内容不再提供；需要时询问用户。"
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


def withdrawn_message_ids(rows, source_ids, versions):
    """旧来源与依赖输出失效；用户的新输入不继承模型读取的记忆依赖。"""
    mutations = {}
    affected_requests = {row["request_id"] for row in rows if row["message_id"] in source_ids}
    for row in rows:
        if mutation := row["message_json"].get("memory_mutation"):
            mutations.setdefault(row["request_id"], set()).add(str(mutation))
    for row in rows:
        if any(
            versions.get(mid) != revision and mid not in mutations.get(row["request_id"], set())
            for mid, revision in row["message_json"].get("memory_refs", {}).items()
        ):
            affected_requests.add(row["request_id"])

    withdrawn = set(source_ids)
    outputs = [row for row in rows if row["message_kind"] != "user_message"]
    while True:
        withdrawn.update(
            row["message_id"] for row in outputs if row["request_id"] in affected_requests
        )
        readers = {
            row["request_id"]
            for row in outputs
            if withdrawn.intersection(row["message_json"].get("source_message_ids", []))
        }
        if readers <= affected_requests:
            return withdrawn
        affected_requests.update(readers)
