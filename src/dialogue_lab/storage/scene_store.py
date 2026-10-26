"""持久保存用户场景；行锁使更新与新建会话遵守相同生命周期规则。"""

from sqlalchemy import delete, func, insert, select, update

from dialogue_lab.sessions.types import SessionError
from dialogue_lab.storage.tables import scenes, sessions


class SceneStore:
    def __init__(self, database):
        self.database = database

    async def list(self):
        async with self.database.engine.connect() as connection:
            return (
                (
                    await connection.execute(
                        select(scenes)
                        .where(scenes.c.status == "active")
                        .order_by(scenes.c.scene_id)
                    )
                )
                .mappings()
                .all()
            )

    async def get(self, scene_id):
        async with self.database.engine.connect() as connection:
            return await get_scene(connection, scene_id)

    async def find_for_session(self, session_id):
        """读取会话所属场景的当前资料；归档场景仍可用于已有会话。"""
        async with self.database.engine.connect() as connection:
            return (
                (
                    await connection.execute(
                        select(scenes)
                        .join(sessions, sessions.c.scene_id == scenes.c.scene_id)
                        .where(sessions.c.session_id == session_id)
                    )
                )
                .mappings()
                .one_or_none()
            )

    async def create(self, values):
        async with self.database.engine.begin() as connection:
            return (
                (await connection.execute(insert(scenes).values(**values).returning(scenes)))
                .mappings()
                .one()
            )

    async def update(self, scene_id, values):
        async with self.database.engine.begin() as connection:
            await get_scene(connection, scene_id, lock=True)
            return (
                (
                    await connection.execute(
                        update(scenes)
                        .where(scenes.c.scene_id == scene_id)
                        .values(**values, updated_at=func.now())
                        .returning(scenes)
                    )
                )
                .mappings()
                .one()
            )

    async def delete(self, scene_id):
        async with self.database.engine.begin() as connection:
            row = await get_scene(connection, scene_id, lock=True)
            used = (
                await connection.execute(
                    select(sessions.c.session_id).where(sessions.c.scene_id == scene_id).limit(1)
                )
            ).first()
            if used:
                await connection.execute(
                    update(scenes)
                    .where(scenes.c.scene_id == scene_id)
                    .values(status="archived", updated_at=func.now())
                )
                return "archived", row
            await connection.execute(delete(scenes).where(scenes.c.scene_id == scene_id))
            return "deleted", row


async def get_scene(connection, scene_id, *, lock=False):
    query = select(scenes).where(scenes.c.scene_id == scene_id)
    row = (await connection.execute(query.with_for_update() if lock else query)).mappings().first()
    if row is None:
        raise SessionError("SCENE_NOT_FOUND", "场景不存在。", 404)
    return row
