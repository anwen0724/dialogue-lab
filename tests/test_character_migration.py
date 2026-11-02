"""在隔离 schema 验证角色改名保留已有记录和会话关联。"""

import asyncio

from alembic import command
from alembic.config import Config
from conftest import TEST_DATABASE_URL
from sqlalchemy import text

from dialogue_lab.storage.database import Database


def test_character_migration_preserves_existing_data_and_can_downgrade(isolated_schema):
    async def sql(statement):
        database = Database(TEST_DATABASE_URL)
        try:
            async with database.engine.begin() as connection:
                assert await connection.scalar(text("SELECT current_schema()")) == isolated_schema
                return (await connection.execute(text(statement))).mappings().all()
        finally:
            await database.close()

    config = Config("alembic.ini")
    command.downgrade(config, "0003")
    before = asyncio.run(sql("SELECT * FROM scenes ORDER BY scene_id"))
    linked = asyncio.run(
        sql("""INSERT INTO sessions(title, scene_id)
        SELECT 'Existing dialogue', scene_id FROM scenes ORDER BY scene_id LIMIT 1
        RETURNING session_id, scene_id""")
    )[0]
    session_id = linked["session_id"]
    try:
        command.upgrade(config, "0004")
        after = asyncio.run(sql("SELECT * FROM characters ORDER BY character_id"))
        expected = [dict(row) for row in before]
        for row in expected:
            row["character_id"] = row.pop("scene_id")
        assert [dict(row) for row in after] == expected
        sessions = asyncio.run(
            sql(f"SELECT session_id, character_id FROM sessions WHERE session_id={session_id}")
        )
        assert sessions[0]["character_id"] == linked["scene_id"]
        inserted = asyncio.run(
            sql("""INSERT INTO characters(
            name, category, character_name, prompt_key)
            VALUES ('New character', 'test', 'Emma', 'rename-migration-test')
            RETURNING character_id""")
        )[0]
        assert inserted["character_id"] > max(row["scene_id"] for row in before)
        command.downgrade(config, "0003")
        restored = asyncio.run(sql(f"SELECT scene_id FROM sessions WHERE session_id={session_id}"))
        assert restored[0]["scene_id"] == linked["scene_id"]
        asyncio.run(
            sql("DELETE FROM scenes WHERE prompt_key='rename-migration-test' RETURNING scene_id")
        )
    finally:
        command.upgrade(config, "head")
        asyncio.run(sql(f"DELETE FROM sessions WHERE session_id={session_id} RETURNING session_id"))
