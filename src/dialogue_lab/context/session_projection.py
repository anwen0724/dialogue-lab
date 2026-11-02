"""把当前路径投影为应用消息；原始聊天读取不经过此投影。"""

from ai import TextContent, message_from_dict

from dialogue_lab.context.messages import CompactionSummary
from dialogue_lab.memory.types import redact_message
from dialogue_lab.sessions.types import SessionError


def project_path(path, models, memory_revision=0, withdrawn=frozenset()):
    """最后一个压缩节点取代其覆盖前缀，之后的原文按路径保留。"""
    projected = []
    for row in path:
        if row["entry_type"] == "compaction":
            if row["memory_revision"] == memory_revision:
                projected = [(row["entry_id"], CompactionSummary(row["summary_text"]))]
        else:
            if row["message_id"] in withdrawn:
                row = redact_message(row)
            projected.append((row["entry_id"], restore_message(row, models)))
    return projected


def restore_message(row, models):
    payload = row["message_json"]
    if row["message_kind"] == "tool_result":
        return message_from_dict(
            {
                "role": "tool_result",
                **{key: payload[key] for key in ("tool_call_id", "name", "content", "is_error")},
            }
        )
    if row["message_kind"] == "user_message":
        return message_from_dict({"role": "user", "content": payload["model_content"]})
    model = models.get_model(payload["provider"], payload["model"])
    if model is None:
        raise SessionError("HISTORY_MODEL_UNAVAILABLE", "历史回复的模型不在当前模型目录中。")
    restored = message_from_dict(
        {
            "role": "assistant",
            "provider": payload["provider"],
            "model": payload["model"],
            "api": model.api,
            "content": payload["content"],
            "usage": payload["usage"] or {},
            "stop_reason": payload["finish_reason"],
            "response_id": payload["response_id"],
            "error": {"code": payload["error_code"], "message": payload["error_message"]}
            if payload["error_code"]
            else None,
        }
    )
    if row["playback_state"] == "interrupted":
        restored.content.append(
            TextContent("\n[应用记录：此条回复的播放被打断，不能假设对方已经听完。]")
        )
    return restored
