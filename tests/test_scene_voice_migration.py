"""在隔离 schema 上验证 0002 已有数据升级及新记录的空值语义。"""

import asyncio

from alembic import command
from alembic.config import Config
from conftest import TEST_DATABASE_URL
from sqlalchemy import text

from dialogue_lab.storage.database import Database


def test_upgrade_backfills_existing_scenes_without_a_default(isolated_schema, monkeypatch):
    async def sql(statement):
        database = Database(TEST_DATABASE_URL)
        try:
            async with database.engine.begin() as connection:
                assert await connection.scalar(text("SELECT current_schema()")) == isolated_schema
                return (await connection.execute(text(statement))).mappings().all()
        finally:
            await database.close()

    command.downgrade(Config("alembic.ini"), "0002")
    before = asyncio.run(sql("SELECT scene_id,name,prompt_key FROM scenes ORDER BY scene_id"))
    monkeypatch.setenv("DIALOGUE_LAB_TTS_VOICE", "longanhuan_v3.1")
    command.upgrade(Config("alembic.ini"), "head")
    after = asyncio.run(
        sql("SELECT scene_id,name,prompt_key,tts_voice FROM scenes ORDER BY scene_id")
    )
    assert [{k: row[k] for k in ("scene_id", "name", "prompt_key")} for row in after] == before
    assert all(row["tts_voice"] == "longanhuan_v3.1" for row in after)
    inserted = asyncio.run(
        sql("""INSERT INTO scenes(name,category,character_name,prompt_key)
        VALUES ('Migration test','test','test','migration-test') RETURNING tts_voice""")
    )
    assert inserted[0]["tts_voice"] is None
    asyncio.run(sql("DELETE FROM scenes WHERE prompt_key='migration-test' RETURNING scene_id"))
