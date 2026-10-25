"""把当前路径投影为应用消息；原始聊天读取不经过此投影。"""

from ai import message_from_dict

from dialogue_lab.context.messages import CompactionSummary
from dialogue_lab.sessions.types import SessionError


def project_path(path, models):
    """最后一个压缩节点取代其覆盖前缀，之后的原文按路径保留。"""
    projected = []
    for row in path:
        if row["entry_type"] == "compaction":
            projected = [(row["entry_id"], CompactionSummary(row["summary_text"]))]
        else:
            projected.append((row["entry_id"], restore_message(row, models)))
    return projected


def restore_message(row, models):
    payload = row["message_json"]
    if row["message_kind"] == "user_message":
        return message_from_dict({"role": "user", "content": payload["model_content"]})
    model = models.get_model(payload["provider"], payload["model"])
    if model is None:
        raise SessionError("HISTORY_MODEL_UNAVAILABLE", "历史回复的模型不在当前模型目录中。")
    return message_from_dict(
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
