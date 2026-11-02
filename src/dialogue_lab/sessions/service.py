"""会话业务入口：请求校验、消息载荷与对外读取结果。"""

from dataclasses import asdict

from dialogue_lab.memory.types import redact_message
from dialogue_lab.sessions.types import SessionError, SessionState, message_view, session_view
from dialogue_lab.storage.memory_store import MemoryStore
from dialogue_lab.storage.session_store import SessionStore


class SessionService:
    def __init__(self, store: SessionStore):
        self.store = store

    async def create(self, title: str, character_id: int | None = None) -> dict:
        return session_view(await self.store.create(title, character_id))

    async def list(self, character_id=None) -> list[dict]:
        return [session_view(row) for row in await self.store.list(character_id)]

    async def path(self, session_id: int):
        await self.store.get(session_id)
        return await self.store.path(session_id)

    async def open(self, session_id: int) -> dict:
        return {
            **session_view(await self.store.get(session_id)),
            "messages": [
                message_view(row)
                for row in await self.store.path(session_id)
                if row["entry_type"] == "message" and visible_message(row)
            ],
        }

    async def find_request(self, session_id, request_id, text, source):
        """重复请求只返回既有消息，不打断当前回复。"""
        row = await self.store.find_user_request(session_id, request_id)
        if row is None:
            return None
        payload = row["message_json"]
        if (
            payload["model_content"] != [{"type": "text", "text": text.strip()}]
            or payload["source"] != source
        ):
            raise SessionError("REQUEST_CONFLICT", "同一请求标识不能用于不同的消息内容。")
        return message_view(row)

    async def submit(self, session_id, request_id, text, source="text"):
        """保存确认输入，返回消息及是否首次提交。"""
        text = text.strip()
        if not text or source not in ("text", "voice", "opening"):
            raise SessionError("INVALID_INPUT", "请提交非空文字或确认后的语音内容。", 422)
        content = [{"type": "text", "text": text}]
        row, created = await self.store.append(
            session_id,
            request_id,
            "user_message",
            {
                "display_content": [] if source == "opening" else content,
                "model_content": content,
                "source": source,
            },
        )
        return message_view(row), created

    async def save_assistant(self, session_id, request_id, message, step=0, memory_refs=None):
        """保存一次模型调用的结果；播放回执独立更新。"""
        payload = {
            "content": [asdict(block) for block in message.content],
            "status": {"aborted": "cancelled", "error": "failed"}.get(
                message.stop_reason, "completed"
            ),
            "provider": message.provider,
            "model": message.model,
            "response_model": None,
            "response_id": message.response_id,
            "usage": asdict(message.usage),
            "finish_reason": message.stop_reason,
            "error_code": message.error.code if message.error else None,
            "error_message": message.error.message if message.error else None,
        }
        if memory_refs:
            payload["memory_refs"] = memory_refs
        row, _ = await self.store.append(session_id, request_id, "assistant_message", payload, step)
        return message_view(row)

    async def state(self, session_id):
        return SessionState.model_validate((await self.store.get(session_id))["session_state"])

    async def record_playback(self, session_id, request_id, state):
        await self.store.record_playback(session_id, request_id, state)

    async def read_history(self, connection, session, session_id, message_ids):
        rows = await self.store.read_history(connection, session, session_id, message_ids)
        character = session["character_id"]
        withdrawn = await MemoryStore(self.store.database).withdrawn_requests(connection, character)
        return {
            "messages": [
                message_view(
                    redact_message(row) if row["request_id"] in withdrawn else row,
                )
                for row in rows
            ]
        }

    async def update_state(self, connection, session, patch):
        """在工具事务内覆盖给定字段，未给定字段保留。"""
        state = SessionState.model_validate({**session["session_state"], **patch})
        await self.store.update_state(connection, session["session_id"], state.model_dump())
        return state.model_dump()

    async def execute_tool(self, session_id, request_id, step, call, operation, signal):
        return await self.store.execute_tool(session_id, request_id, step, call, operation, signal)

    async def close_pending_tools(self, session_id):
        await self.store.close_pending_tools(session_id)


def visible_message(row):
    if row["message_kind"] == "tool_result":
        return False
    return (
        row["message_kind"] != "assistant_message"
        or any(
            b["type"] == "text" and b.get("text") for b in row["message_json"].get("content", [])
        )
        or row["message_json"].get("status") in ("failed", "cancelled")
    )
