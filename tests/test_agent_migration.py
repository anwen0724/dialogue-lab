"""在隔离库验证旧会话升级、多步唯一性和用户请求去重约束。"""

import asyncio
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from conftest import TEST_DATABASE_URL
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from dialogue_lab.storage.database import Database


def test_agent_migration_preserves_old_messages_and_allows_multiple_steps(isolated_schema):
    async def sql(statement, parameters=None):
        database = Database(TEST_DATABASE_URL)
        try:
            async with database.engine.begin() as connection:
                assert await connection.scalar(text("SELECT current_schema()")) == isolated_schema
                result = await connection.execute(text(statement), parameters or {})
                return result.mappings().all() if result.returns_rows else []
        finally:
            await database.close()

    config = Config("alembic.ini")
    command.downgrade(config, "0004")
    sid = asyncio.run(sql("INSERT INTO sessions(title) VALUES ('Existing') RETURNING session_id"))[
        0
    ]["session_id"]
    parameters = {"sid": sid, "request": uuid4()}
    asyncio.run(
        sql(
            """
        INSERT INTO session_messages(session_id, request_id, message_kind, message_json)
        VALUES (:sid, :request, 'user_message',
                '{"model_content":[{"type":"text","text":"Hello"}]}')
    """,
            parameters,
        )
    )
    try:
        command.upgrade(config, "head")
        state = asyncio.run(
            sql("SELECT session_state FROM sessions WHERE session_id=:sid", parameters)
        )[0]["session_state"]
        assert state == {"activity": None, "instructions": []}
        old = asyncio.run(sql("SELECT * FROM session_messages WHERE session_id=:sid", parameters))[
            0
        ]
        assert old["step"] == 0
        assert old["message_json"]["model_content"][0]["text"] == "Hello"
        insert = """INSERT INTO session_messages(
            session_id, request_id, message_kind, step, message_json)
            VALUES (:sid, :request, :kind, :step, '{}')"""
        for step in (0, 1):
            asyncio.run(sql(insert, {**parameters, "kind": "assistant_message", "step": step}))
        with pytest.raises(IntegrityError):
            asyncio.run(sql(insert, {**parameters, "kind": "assistant_message", "step": 1}))
        with pytest.raises(IntegrityError):
            asyncio.run(sql(insert, {**parameters, "kind": "user_message", "step": 1}))
        with pytest.raises(IntegrityError):
            asyncio.run(sql(insert, {**parameters, "kind": "user_message", "step": 0}))
    finally:
        command.upgrade(config, "head")
        asyncio.run(sql("DELETE FROM session_messages WHERE session_id=:sid", parameters))
        asyncio.run(sql("DELETE FROM sessions WHERE session_id=:sid", parameters))
