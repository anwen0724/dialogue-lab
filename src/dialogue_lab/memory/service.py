"""长期记忆的业务入口；写操作使用工具事务。"""

from datetime import datetime

from dialogue_lab.memory.types import MemoryExcerpt
from dialogue_lab.sessions.types import SessionError


class MemoryService:
    def __init__(self, store):
        self.store = store

    async def core(self, session_id):
        return [
            MemoryExcerpt(
                row["id"],
                row["content"],
                row["revision"],
                row["source_message_ids"],
            )
            for row in await self.store.core(session_id)
        ]

    async def save(self, connection, session, request_id, **arguments):
        return await self.store.save(connection, session, request_id, **arguments)

    async def forget(self, connection, session, memory_id):
        return await self.store.forget(connection, session, memory_id)

    async def projection_state(self, session_id):
        return await self.store.projection_state(session_id)

    async def search(self, connection, session, query, after=None, before=None):
        try:
            dates = [
                datetime.fromisoformat(value) if value is not None else None
                for value in (after, before)
            ]
            if any(value is not None and value.tzinfo is None for value in dates):
                raise ValueError
            if all(dates) and dates[0] >= dates[1]:
                raise ValueError
        except ValueError:
            raise SessionError(
                "INVALID_TIME_RANGE", "时间范围应包含时区，开始应早于结束。"
            ) from None
        return {
            "matches": await self.store.search(
                connection,
                session["character_id"],
                query,
                *dates,
            )
        }
