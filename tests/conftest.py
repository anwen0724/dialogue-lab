"""在现有 PostgreSQL 的独立 schema 验证，结束后只清理本次测试数据。"""

import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from dialogue_lab.config import Settings
from dialogue_lab.sessions.service import SessionService
from dialogue_lab.storage.database import Database
from dialogue_lab.storage.session_store import SessionStore

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    Settings().database_url.get_secret_value(),
)


@pytest.fixture(scope="session")
def isolated_schema():
    """每轮测试独占一个 schema；业务库的 public 不进入搜索路径。"""
    schema = "dialogue_" + uuid4().hex + "_test"

    async def execute(sql):
        database = Database(TEST_DATABASE_URL)
        try:
            async with database.engine.begin() as connection:
                await connection.execute(text(sql))
        finally:
            await database.close()

    def connect(dialect, record, args, parameters):
        parameters["server_settings"] = {"search_path": schema}

    previous = os.environ.get("DIALOGUE_LAB_DATABASE_URL")
    asyncio.run(execute(f'CREATE SCHEMA "{schema}"'))
    event.listen(Engine, "do_connect", connect)
    os.environ["DIALOGUE_LAB_DATABASE_URL"] = TEST_DATABASE_URL
    try:
        command.upgrade(Config("alembic.ini"), "head")
        yield schema
    finally:
        event.remove(Engine, "do_connect", connect)
        if previous is None:
            os.environ.pop("DIALOGUE_LAB_DATABASE_URL", None)
        else:
            os.environ["DIALOGUE_LAB_DATABASE_URL"] = previous
        asyncio.run(execute(f'DROP SCHEMA "{schema}" CASCADE'))


@pytest_asyncio.fixture
async def database(isolated_schema):
    database = Database(TEST_DATABASE_URL)
    async with database.engine.connect() as connection:
        actual = await connection.scalar(text("SELECT current_schema()"))
        if actual != isolated_schema:
            await database.close()
            raise RuntimeError("测试连接没有进入隔离 schema，拒绝运行和清理数据。")
    yield database
    # 保留迁移及初始化场景，清理每项测试创建的会话。
    async with database.engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE sessions, session_messages, session_entries, session_compactions CASCADE"
            )
        )
    await database.close()


@pytest_asyncio.fixture
async def session_service(database):
    return SessionService(SessionStore(database))
