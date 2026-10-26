"""会话 API 和核心服务共用的边界输入与业务错误。"""

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    scene_id: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=200)


class SessionError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code = code
        self.status = status


def session_view(row) -> dict:
    """bigint 对外编码为字符串，防止浏览器丢失精度。"""
    return {
        "session_id": str(row["session_id"]),
        "title": row["title"],
        "scene_id": str(row["scene_id"]) if row["scene_id"] is not None else None,
        "message_count": row.get("message_count", 0),
        "latest_message": row.get("latest_message", ""),
        "status": row["status"],
        "model_selection": row["model_selection"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def message_view(row) -> dict:
    return {
        "message_id": str(row["message_id"]),
        "session_id": str(row["session_id"]),
        "request_id": str(row["request_id"]),
        "message_kind": row["message_kind"],
        "message_json": row["message_json"],
    }
