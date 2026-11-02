"""在调用者的短事务内读取和写入角色记忆。"""

from sqlalchemy import func, insert, or_, select, update

from dialogue_lab.sessions.types import SessionError
from dialogue_lab.storage.tables import characters, memories, memory_sources, messages, sessions


class MemoryStore:
    def __init__(self, database):
        self.database = database

    async def core(self, session_id):
        async with self.database.engine.connect() as connection:
            character_id = await connection.scalar(
                select(sessions.c.character_id).where(sessions.c.session_id == session_id)
            )
            if character_id is None:
                return []
            rows = (
                (
                    await connection.execute(
                        select(memories)
                        .where(
                            memories.c.character_id == character_id,
                            memories.c.status == "active",
                            memories.c.is_core,
                        )
                        .order_by(memories.c.memory_id)
                    )
                )
                .mappings()
                .all()
            )
            return [await self.view(connection, row) for row in rows]

    async def save(
        self,
        connection,
        session,
        request_id,
        content,
        is_core=False,
        source_message_ids=None,
        memory_id=None,
    ):
        if session["character_id"] is None:
            raise SessionError("CHARACTER_REQUIRED", "此会话没有关联角色。")
        query = (
            select(messages.c.message_id, messages.c.request_id)
            .join(
                sessions,
                messages.c.session_id == sessions.c.session_id,
            )
            .where(
                sessions.c.character_id == session["character_id"],
                messages.c.message_kind == "user_message",
            )
        )
        if source_message_ids is None:
            query = query.where(
                messages.c.session_id == session["session_id"], messages.c.request_id == request_id
            )
        else:
            query = query.where(messages.c.message_id.in_(source_message_ids))
        source_rows = (await connection.execute(query)).mappings().all()
        source_ids = [row["message_id"] for row in source_rows]
        if not source_ids or (
            source_message_ids is not None and set(source_ids) != set(source_message_ids)
        ):
            raise SessionError("INVALID_MEMORY_SOURCE", "记忆来源不属于当前角色的用户消息。")
        withdrawn = await self.withdrawn_requests(connection, session["character_id"])
        if any(row["request_id"] in withdrawn for row in source_rows):
            raise SessionError("MEMORY_SOURCE_WITHDRAWN", "来源内容已撤回，不能重新保存。")
        if memory_id is None:
            statement = insert(memories).values(
                character_id=session["character_id"],
                content=content.strip(),
                is_core=is_core,
            )
        else:
            await self.get_owned(connection, session["character_id"], memory_id)
            statement = (
                update(memories)
                .where(memories.c.memory_id == memory_id)
                .values(
                    content=content.strip(),
                    is_core=is_core,
                    revision=memories.c.revision + 1,
                    updated_at=func.now(),
                )
            )
            await self.invalidate(connection, session["character_id"])
        row = (await connection.execute(statement.returning(memories))).mappings().one()
        await connection.execute(
            insert(memory_sources),
            [
                {"memory_id": row["memory_id"], "revision": row["revision"], "message_id": mid}
                for mid in source_ids
            ],
        )
        return await self.view(connection, row)

    async def get_owned(self, connection, character_id, memory_id):
        row = (
            (
                await connection.execute(
                    select(memories)
                    .where(
                        memories.c.character_id == character_id,
                        memories.c.memory_id == memory_id,
                        memories.c.status == "active",
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise SessionError("MEMORY_NOT_FOUND", "当前角色没有这条有效记忆。")
        return row

    async def invalidate(self, connection, character_id):
        await connection.execute(
            update(characters)
            .where(
                characters.c.character_id == character_id,
            )
            .values(memory_revision=characters.c.memory_revision + 1)
        )

    async def forget(self, connection, session, memory_id):
        await self.get_owned(connection, session["character_id"], memory_id)
        await connection.execute(
            update(memories)
            .where(memories.c.memory_id == memory_id)
            .values(
                content=None,
                is_core=False,
                status="forgotten",
                revision=memories.c.revision + 1,
                updated_at=func.now(),
            )
        )
        await self.invalidate(connection, session["character_id"])
        return {"forgotten": memory_id}

    async def withdrawn_requests(self, connection, character_id):
        """撤回来源轮次及读取过旧版本材料的轮次，原始记录不变。"""
        withdrawn = set(
            (
                await connection.execute(
                    select(messages.c.request_id)
                    .join(
                        memory_sources,
                        memory_sources.c.message_id == messages.c.message_id,
                    )
                    .join(memories, memories.c.memory_id == memory_sources.c.memory_id)
                    .where(
                        memories.c.character_id == character_id,
                        or_(
                            memories.c.status == "forgotten",
                            memory_sources.c.revision != memories.c.revision,
                        ),
                    )
                )
            ).scalars()
        )
        versions = {
            str(row.memory_id): row.revision
            for row in (
                await connection.execute(
                    select(
                        memories.c.memory_id,
                        memories.c.revision,
                    ).where(memories.c.character_id == character_id, memories.c.status == "active")
                )
            ).all()
        }
        rows = (
            await connection.execute(
                select(messages.c.request_id, messages.c.message_json)
                .join(sessions, sessions.c.session_id == messages.c.session_id)
                .where(sessions.c.character_id == character_id)
            )
        ).all()
        mutations = {}
        for request_id, payload in rows:
            if mutation := payload.get("memory_mutation"):
                mutations.setdefault(request_id, set()).add(str(mutation))
        for request_id, payload in rows:
            if any(
                versions.get(mid) != revision and mid not in mutations.get(request_id, set())
                for mid, revision in payload.get("memory_refs", {}).items()
            ):
                withdrawn.add(request_id)
        # 读取原文的结果也有来源，撤回沿读取依赖传递，但不删除原始消息。
        source_requests = dict(
            (
                await connection.execute(
                    select(
                        messages.c.message_id,
                        messages.c.request_id,
                    )
                    .join(sessions, sessions.c.session_id == messages.c.session_id)
                    .where(
                        sessions.c.character_id == character_id,
                    )
                )
            ).all()
        )
        changed = True
        while changed:
            changed = False
            for request_id, payload in rows:
                if request_id not in withdrawn and any(
                    source_requests.get(mid) in withdrawn
                    for mid in payload.get("source_message_ids", [])
                ):
                    withdrawn.add(request_id)
                    changed = True
        return withdrawn

    async def projection_state(self, session_id):
        async with self.database.engine.connect() as connection:
            character = (
                (
                    await connection.execute(
                        select(characters)
                        .join(
                            sessions,
                            sessions.c.character_id == characters.c.character_id,
                        )
                        .where(sessions.c.session_id == session_id)
                    )
                )
                .mappings()
                .first()
            )
            if character is None:
                return 0, set()
            return character["memory_revision"], await self.withdrawn_requests(
                connection,
                character["character_id"],
            )

    async def search(self, connection, character_id, query, after=None, before=None):
        statement = select(memories).where(
            memories.c.character_id == character_id,
            memories.c.status == "active",
            memories.c.content.icontains(query.strip(), autoescape=True),
        )
        if after is not None:
            statement = statement.where(memories.c.created_at >= after)
        if before is not None:
            statement = statement.where(memories.c.created_at < before)
        rows = (
            (
                await connection.execute(
                    statement.order_by(
                        memories.c.updated_at.desc(),
                        memories.c.memory_id.desc(),
                    ).limit(10)
                )
            )
            .mappings()
            .all()
        )
        return [await self.view(connection, row) for row in rows]

    async def view(self, connection, row):
        sources = (
            (
                await connection.execute(
                    select(
                        memory_sources.c.message_id,
                        messages.c.session_id,
                    )
                    .join(messages, messages.c.message_id == memory_sources.c.message_id)
                    .where(
                        memory_sources.c.memory_id == row["memory_id"],
                        memory_sources.c.revision == row["revision"],
                    )
                    .order_by(memory_sources.c.message_id)
                )
            )
            .mappings()
            .all()
        )
        return {
            "id": row["memory_id"],
            "content": row["content"],
            "revision": row["revision"],
            "is_core": row["is_core"],
            "source_message_ids": [s["message_id"] for s in sources],
            "sources": [dict(s) for s in sources],
        }
