"""通过应用公开接口验证会话保存；使用隔离的 PostgreSQL 数据库。"""

from uuid import uuid4

import pytest
from ai import AssistantMessage, TextContent
from conftest import TEST_DATABASE_URL
from fastapi.testclient import TestClient

from dialogue_lab.main import create_app
from dialogue_lab.sessions.types import SessionError


@pytest.mark.usefixtures("database")
def test_created_session_can_be_reopened(monkeypatch):
    monkeypatch.setenv(
        "DIALOGUE_LAB_DATABASE_URL",
        TEST_DATABASE_URL,
    )
    with TestClient(create_app()) as client:
        response = client.post("/api/sessions", json={"title": "英语练习"})
        assert response.status_code == 201
        session = response.json()
        assert isinstance(session["session_id"], str)
        opened = client.get(f"/api/sessions/{session['session_id']}")
        assert opened.status_code == 200
        assert opened.json()["title"] == "英语练习"
        assert opened.json()["messages"] == []
        listing = client.get("/api/sessions")
        assert listing.status_code == 200
        assert any(item["session_id"] == session["session_id"] for item in listing.json())


@pytest.mark.asyncio
async def test_confirmed_input_is_saved_once_and_reopened(session_service):
    session = await session_service.create("练习")
    session_id = int(session["session_id"])
    request_id = uuid4()
    saved, created = await session_service.submit(session_id, request_id, "Hello")
    repeated, repeated_created = await session_service.submit(session_id, request_id, "Hello")
    assert created is True
    assert repeated_created is False
    assert repeated == saved
    opened = await session_service.open(session_id)
    assert opened["messages"] == [saved]
    assert saved["message_kind"] == "user_message"
    assert saved["message_json"]["model_content"] == [{"type": "text", "text": "Hello"}]


@pytest.mark.asyncio
async def test_cancelled_reply_is_saved_between_its_input_and_next_input(session_service):
    session_id = int((await session_service.create("练习"))["session_id"])
    request = uuid4()
    await session_service.submit(session_id, request, "Hello")
    await session_service.save_assistant(
        session_id,
        request,
        AssistantMessage(
            "test",
            "dialogue",
            "test",
            content=[TextContent("Partial")],
            stop_reason="aborted",
        ),
    )
    await session_service.submit(session_id, uuid4(), "Next")
    opened = await session_service.open(session_id)
    assert [m["message_kind"] for m in opened["messages"]] == [
        "user_message",
        "assistant_message",
        "user_message",
    ]
    assert opened["messages"][1]["message_json"]["content"][0]["text"] == "Partial"
    assert opened["messages"][1]["message_json"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_reusing_request_id_for_different_input_is_rejected(session_service):
    session_id = int((await session_service.create("练习"))["session_id"])
    request = uuid4()
    await session_service.submit(session_id, request, "Original")
    with pytest.raises(SessionError) as caught:
        await session_service.submit(session_id, request, "Different")
    assert caught.value.code == "REQUEST_CONFLICT"
    assert len((await session_service.open(session_id))["messages"]) == 1


@pytest.mark.asyncio
async def test_cross_session_reference_rolls_back_message_and_pointer(database, session_service):
    from sqlalchemy import func, insert, select, update
    from sqlalchemy.exc import IntegrityError

    from dialogue_lab.storage.tables import entries, messages, sessions

    first = int((await session_service.create("First"))["session_id"])
    second = int((await session_service.create("Second"))["session_id"])
    await session_service.submit(first, uuid4(), "Existing")
    foreign_entry = (await session_service.path(first))[-1]["entry_id"]
    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            message_id = (
                await connection.execute(
                    insert(messages)
                    .values(
                        session_id=second,
                        request_id=uuid4(),
                        message_kind="user_message",
                        message_json={"model_content": []},
                    )
                    .returning(messages.c.message_id)
                )
            ).scalar_one()
            await connection.execute(
                insert(entries).values(
                    session_id=second,
                    parent_entry_id=foreign_entry,
                    entry_type="message",
                    message_id=message_id,
                )
            )
    async with database.engine.connect() as connection:
        count = (
            await connection.execute(
                select(func.count()).select_from(messages).where(messages.c.session_id == second)
            )
        ).scalar_one()
    assert count == 0
    assert (await session_service.open(second))["messages"] == []
    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            await connection.execute(
                update(sessions)
                .where(sessions.c.session_id == second)
                .values(active_entry_id=foreign_entry)
            )
    assert await session_service.path(second) == []
