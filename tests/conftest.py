"""测试只连接隔离数据库；数据库由 Alembic 预先迁移。"""

import os

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url

from dialogue_lab.sessions.service import SessionService
from dialogue_lab.storage.database import Database
from dialogue_lab.storage.session_store import SessionStore

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://dialogue_test:dialogue_test@127.0.0.1:55432/dialogue_test",
)


@pytest_asyncio.fixture
async def database():
    if not (make_url(TEST_DATABASE_URL).database or "").endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL 必须使用专用的 *_test 数据库。")
    database = Database(TEST_DATABASE_URL)
    yield database
    # 本 fixture 只用于专用测试库，保留迁移版本，清理每次测试的数据。
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
