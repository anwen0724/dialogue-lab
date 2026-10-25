"""在短事务中读取和保存会话；后续消息写入也从这里维护路径。"""

from sqlalchemy import func, insert, select, update

from dialogue_lab.sessions.types import SessionError
from dialogue_lab.storage.database import Database
from dialogue_lab.storage.tables import compactions, entries, messages, sessions


class SessionStore:
    def __init__(self, database: Database):
        self.database = database

    async def create(self, title: str):
        async with self.database.engine.begin() as connection:
            return (
                (await connection.execute(insert(sessions).values(title=title).returning(sessions)))
                .mappings()
                .one()
            )

    async def get(self, session_id: int):
        async with self.database.engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(sessions).where(sessions.c.session_id == session_id)
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise SessionError("SESSION_NOT_FOUND", "会话不存在。", 404)
            return row

    async def list(self):
        async with self.database.engine.connect() as connection:
            return (
                (
                    await connection.execute(
                        select(sessions).order_by(
                            sessions.c.updated_at.desc(), sessions.c.session_id.desc()
                        )
                    )
                )
                .mappings()
                .all()
            )

    async def append(self, session_id, request_id, kind, payload):
        """会话行锁串行化路径追加；请求去重和路径更新在同一短事务中完成。"""
        async with self.database.engine.begin() as connection:
            session = await lock_session(connection, session_id)
            existing = (
                (
                    await connection.execute(
                        select(messages).where(
                            messages.c.session_id == session_id,
                            messages.c.request_id == request_id,
                            messages.c.message_kind == kind,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if existing["message_json"] != payload:
                    raise SessionError("REQUEST_CONFLICT", "同一请求标识不能用于不同的消息内容。")
                return existing, False
            row = (
                (
                    await connection.execute(
                        insert(messages)
                        .values(
                            session_id=session_id,
                            request_id=request_id,
                            message_kind=kind,
                            message_json=payload,
                            completed_at=func.now(),
                        )
                        .returning(messages)
                    )
                )
                .mappings()
                .one()
            )
            entry_id = (
                await connection.execute(
                    insert(entries)
                    .values(
                        session_id=session_id,
                        parent_entry_id=session["active_entry_id"],
                        entry_type="message",
                        message_id=row["message_id"],
                    )
                    .returning(entries.c.entry_id)
                )
            ).scalar_one()
            await connection.execute(
                update(sessions)
                .where(sessions.c.session_id == session_id)
                .values(active_entry_id=entry_id, updated_at=func.now())
            )
            return row, True

    async def path(self, session_id):
        """一次一致性读取获取当前路径；返回根到叶，不用主键或时间猜顺序。"""
        async with self.database.engine.connect() as connection:
            path = (
                select(entries)
                .join(sessions, sessions.c.active_entry_id == entries.c.entry_id)
                .where(sessions.c.session_id == session_id)
                .cte("path", recursive=True)
            )
            path = path.union_all(
                select(entries).join(path, entries.c.entry_id == path.c.parent_entry_id)
            )
            rows = (
                (
                    await connection.execute(
                        select(
                            path,
                            messages.c.request_id,
                            messages.c.message_kind,
                            messages.c.message_json,
                            messages.c.created_at.label("message_created_at"),
                            messages.c.completed_at,
                            compactions.c.summary_text,
                        )
                        .outerjoin(messages, path.c.message_id == messages.c.message_id)
                        .outerjoin(compactions, path.c.compaction_id == compactions.c.compaction_id)
                    )
                )
                .mappings()
                .all()
            )
        # 父节点唯一，根到叶由连接关系决定；压缩节点仍保留覆盖前缀供原始记录读取。
        by_parent = {row["parent_entry_id"]: row for row in rows}
        ordered = []
        parent = None
        while parent in by_parent:
            row = by_parent[parent]
            ordered.append(row)
            parent = row["entry_id"]
        return ordered


async def lock_session(connection, session_id):
    """只在数据库变更期间持锁，模型和语音调用不能持有该锁。"""
    row = (
        (
            await connection.execute(
                select(sessions).where(sessions.c.session_id == session_id).with_for_update()
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise SessionError("SESSION_NOT_FOUND", "会话不存在。", 404)
    if row["status"] != "active":
        raise SessionError("SESSION_ARCHIVED", "已归档的会话不能继续提交。")
    return row
