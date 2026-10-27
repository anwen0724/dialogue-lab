"""持久保存用户角色；行锁使更新与新建会话遵守相同生命周期规则。"""

from sqlalchemy import delete, func, insert, select, update

from dialogue_lab.sessions.types import SessionError
from dialogue_lab.storage.tables import characters, sessions


class CharacterStore:
    def __init__(self, database):
        self.database = database

    async def list(self, *, include_archived=False):
        query = select(characters).order_by(characters.c.character_id)
        if not include_archived:
            query = query.where(characters.c.status == "active")
        async with self.database.engine.connect() as connection:
            return (await connection.execute(query)).mappings().all()

    async def get(self, character_id):
        async with self.database.engine.connect() as connection:
            return await get_character(connection, character_id)

    async def find_for_session(self, session_id):
        """读取会话所属角色的当前资料；归档角色仍可用于已有会话。"""
        async with self.database.engine.connect() as connection:
            return (
                (
                    await connection.execute(
                        select(characters)
                        .join(sessions, sessions.c.character_id == characters.c.character_id)
                        .where(sessions.c.session_id == session_id)
                    )
                )
                .mappings()
                .one_or_none()
            )

    async def create(self, values):
        async with self.database.engine.begin() as connection:
            return (
                (
                    await connection.execute(
                        insert(characters).values(**values).returning(characters)
                    )
                )
                .mappings()
                .one()
            )

    async def update(self, character_id, values):
        async with self.database.engine.begin() as connection:
            await get_character(connection, character_id, lock=True)
            return (
                (
                    await connection.execute(
                        update(characters)
                        .where(characters.c.character_id == character_id)
                        .values(**values, updated_at=func.now())
                        .returning(characters)
                    )
                )
                .mappings()
                .one()
            )

    async def delete(self, character_id):
        async with self.database.engine.begin() as connection:
            row = await get_character(connection, character_id, lock=True)
            used = (
                await connection.execute(
                    select(sessions.c.session_id)
                    .where(sessions.c.character_id == character_id)
                    .limit(1)
                )
            ).first()
            if used:
                await connection.execute(
                    update(characters)
                    .where(characters.c.character_id == character_id)
                    .values(status="archived", updated_at=func.now())
                )
                return "archived", row
            await connection.execute(
                delete(characters).where(characters.c.character_id == character_id)
            )
            return "deleted", row


async def get_character(connection, character_id, *, lock=False):
    query = select(characters).where(characters.c.character_id == character_id)
    row = (await connection.execute(query.with_for_update() if lock else query)).mappings().first()
    if row is None:
        raise SessionError("CHARACTER_NOT_FOUND", "角色不存在。", 404)
    return row
