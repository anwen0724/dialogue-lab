"""会话业务入口：请求校验、消息载荷与对外读取结果。"""

from dataclasses import asdict

from dialogue_lab.sessions.types import SessionError, message_view, session_view
from dialogue_lab.storage.session_store import SessionStore


class SessionService:
    def __init__(self, store: SessionStore):
        self.store = store

    async def create(self, title: str, scene_id: int | None = None) -> dict:
        return session_view(await self.store.create(title, scene_id))

    async def list(self, scene_id=None) -> list[dict]:
        return [session_view(row) for row in await self.store.list(scene_id)]

    async def path(self, session_id: int):
        await self.store.get(session_id)
        return await self.store.path(session_id)

    async def open(self, session_id: int) -> dict:
        return {
            **session_view(await self.store.get(session_id)),
            "messages": [
                message_view(row)
                for row in await self.store.path(session_id)
                if row["entry_type"] == "message"
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

    async def save_assistant(self, session_id, request_id, message):
        """仅在生成结束后保存结果；语音播放状态不写入消息。"""
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
        row, _ = await self.store.append(session_id, request_id, "assistant_message", payload)
        return message_view(row)
