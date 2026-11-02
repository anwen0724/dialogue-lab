"""在短事务中读取和保存会话；后续消息写入也从这里维护路径。"""

import asyncio
from dataclasses import asdict

from ai import ToolResultMessage
from sqlalchemy import func, insert, literal, select, update

from dialogue_lab.sessions.types import SessionError
from dialogue_lab.storage.character_store import get_character
from dialogue_lab.storage.database import Database
from dialogue_lab.storage.tables import compactions, entries, messages, sessions


class SessionStore:
    def __init__(self, database: Database):
        self.database = database

    async def create(self, title: str, character_id=None):
        async with self.database.engine.begin() as connection:
            if character_id is not None:
                character = await get_character(connection, character_id, lock=True)
                if character["status"] != "active":
                    raise SessionError("CHARACTER_ARCHIVED", "已归档的角色不能新建会话。")
            return (
                (
                    await connection.execute(
                        insert(sessions)
                        .values(title=title, character_id=character_id)
                        .returning(sessions)
                    )
                )
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

    async def list(self, character_id=None):
        """一次列表读取加一次路径查询，避免逐个会话查询消息。"""
        query = select(sessions).order_by(
            sessions.c.updated_at.desc(), sessions.c.session_id.desc()
        )
        if character_id is not None:
            query = query.where(sessions.c.character_id == character_id)
        async with self.database.engine.connect() as connection:
            rows = [dict(row) for row in (await connection.execute(query)).mappings()]
            if not rows:
                return rows
            path = (
                select(entries, literal(0).label("depth"))
                .join(sessions, sessions.c.active_entry_id == entries.c.entry_id)
                .where(sessions.c.session_id.in_([row["session_id"] for row in rows]))
                .cte("listing_path", recursive=True)
            )
            path = path.union_all(
                select(entries, (path.c.depth + 1).label("depth")).join(
                    path, entries.c.entry_id == path.c.parent_entry_id
                )
            )
            content = (
                await connection.execute(
                    select(path.c.session_id, messages.c.message_kind, messages.c.message_json)
                    .join(messages, path.c.message_id == messages.c.message_id)
                    .order_by(path.c.depth)
                )
            ).mappings()
            lookup = {row["session_id"]: row for row in rows}
            for row in rows:
                row.update(message_count=0, latest_message="")
            for message in content:
                payload = message["message_json"]
                if (
                    payload.get("source") == "opening"
                    or message["message_kind"] == "tool_result"
                    or (
                        message["message_kind"] == "assistant_message"
                        and payload.get("status") not in ("failed", "cancelled")
                        and not any(
                            b["type"] == "text" and b.get("text")
                            for b in payload.get("content", [])
                        )
                    )
                ):
                    continue
                row = lookup[message["session_id"]]
                blocks = payload.get("display_content", payload.get("content", []))
                text = "".join(block.get("text", "") for block in blocks if block["type"] == "text")
                if row["message_count"] == 0:
                    row["latest_message"] = text[:160]
                row["message_count"] += 1
            return rows

    async def find_user_request(self, session_id, request_id):
        async with self.database.engine.connect() as connection:
            return (
                (
                    await connection.execute(
                        select(messages).where(
                            messages.c.session_id == session_id,
                            messages.c.request_id == request_id,
                            messages.c.message_kind == "user_message",
                        )
                    )
                )
                .mappings()
                .first()
            )

    async def append(self, session_id, request_id, kind, payload, step=0):
        """会话行锁串行化去重、消息和路径追加。"""
        async with self.database.engine.begin() as connection:
            session = await lock_session(connection, session_id)
            return await self.append_locked(connection, session, request_id, kind, payload, step)

    async def append_locked(self, connection, session, request_id, kind, payload, step=0):
        """调用者持有会话锁；工具变更与结果共享该事务。"""
        session_id = session["session_id"]
        existing = (
            (
                await connection.execute(
                    select(messages).where(
                        messages.c.session_id == session_id,
                        messages.c.request_id == request_id,
                        messages.c.message_kind == kind,
                        messages.c.step == step,
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
        # 只有首条真实输入能改标题；应用开场不算用户发言。
        title = session["title"]
        if (
            kind == "user_message"
            and payload.get("source") != "opening"
            and session["character_id"]
        ):
            previous = (
                await connection.execute(
                    select(messages.c.message_id)
                    .where(
                        messages.c.session_id == session_id,
                        messages.c.message_kind == "user_message",
                        messages.c.message_json["source"].astext != "opening",
                    )
                    .limit(1)
                )
            ).first()
            if previous is None:
                title = payload["model_content"][0]["text"][:30]
        row = (
            (
                await connection.execute(
                    insert(messages)
                    .values(
                        session_id=session_id,
                        request_id=request_id,
                        message_kind=kind,
                        step=step,
                        playback_state="unconfirmed" if kind == "assistant_message" else None,
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
            .values(active_entry_id=entry_id, updated_at=func.now(), title=title)
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
                            messages.c.playback_state,
                            compactions.c.summary_text,
                            compactions.c.memory_revision,
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

    async def read_history(self, connection, session, session_id, message_ids):
        character = await connection.scalar(
            select(sessions.c.character_id).where(
                sessions.c.session_id == session_id,
            )
        )
        if character is None or character != session["character_id"]:
            raise SessionError("HISTORY_SCOPE", "只能读取当前角色的历史。")
        rows = (
            (
                await connection.execute(
                    select(messages)
                    .where(
                        messages.c.session_id == session_id,
                        messages.c.message_id.in_(message_ids),
                        messages.c.message_kind.in_(["user_message", "assistant_message"]),
                    )
                    .order_by(messages.c.message_id)
                )
            )
            .mappings()
            .all()
        )
        if len(rows) != len(set(message_ids)):
            raise SessionError("HISTORY_NOT_FOUND", "指定的历史消息不存在。")
        return rows

    async def update_state(self, connection, session_id, state):
        await connection.execute(
            update(sessions).where(sessions.c.session_id == session_id).values(session_state=state)
        )

    async def record_playback(self, session_id, request_id, state):
        async with self.database.engine.begin() as connection:
            await connection.execute(
                update(messages)
                .where(
                    messages.c.session_id == session_id,
                    messages.c.request_id == request_id,
                    messages.c.message_kind == "assistant_message",
                    messages.c.playback_state == "unconfirmed",
                )
                .values(playback_state=state)
            )

    async def execute_tool(self, session_id, request_id, step, call, operation, signal):
        """工具结果和业务变更原子提交；同一步重入只返回原结果。"""
        async with self.database.engine.begin() as connection:
            session = await lock_session(connection, session_id)
            existing = (
                (
                    await connection.execute(
                        select(messages).where(
                            messages.c.session_id == session_id,
                            messages.c.request_id == request_id,
                            messages.c.message_kind == "tool_result",
                            messages.c.step == step,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                payload = existing["message_json"]
                if payload["tool_call_id"] != call.id or payload["name"] != call.name:
                    raise SessionError("REQUEST_CONFLICT", "工具调用标识冲突。")
                return payload
            result = await operation(connection, session)
            if signal and signal.aborted:
                raise asyncio.CancelledError
            await self.append_locked(
                connection,
                session,
                request_id,
                "tool_result",
                result,
                step,
            )
            if signal and signal.aborted:
                raise asyncio.CancelledError
            return result

    async def close_pending_tools(self, session_id):
        """结束中断调用，只补取消结果，不重放写入操作。"""
        async with self.database.engine.begin() as connection:
            session = await lock_session(connection, session_id)
            rows = (
                (
                    await connection.execute(
                        select(messages)
                        .where(messages.c.session_id == session_id)
                        .order_by(messages.c.message_id)
                    )
                )
                .mappings()
                .all()
            )
            completed = {
                (r["request_id"], r["message_json"]["tool_call_id"])
                for r in rows
                if r["message_kind"] == "tool_result"
            }
            steps = {}
            for row in rows:
                request_id = row["request_id"]
                steps[request_id] = max(steps.get(request_id, 0), row["step"] + 1)
            for row in rows:
                if row["message_kind"] != "assistant_message":
                    continue
                for block in row["message_json"]["content"]:
                    key = (row["request_id"], block.get("id"))
                    if block["type"] != "tool_call" or key in completed:
                        continue
                    payload = asdict(
                        ToolResultMessage(
                            block["id"],
                            block["name"],
                            '{"code":"TOOL_NOT_EXECUTED","message":"执行已结束，未执行此调用。"}',
                            is_error=True,
                        )
                    )
                    await self.append_locked(
                        connection,
                        session,
                        row["request_id"],
                        "tool_result",
                        payload,
                        steps[row["request_id"]],
                    )
                    steps[row["request_id"]] += 1
                    completed.add(key)
                    session = await lock_session(connection, session_id)


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
