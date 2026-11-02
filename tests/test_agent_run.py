"""通过会话调度入口验证工具循环；只替换外部模型供应商。"""

import asyncio
import json
from uuid import uuid4

import pytest
from ai import AbortController, AssistantMessage, ToolCall
from model_provider import ScriptedAdapter
from model_provider import test_models as make_models
from sqlalchemy import event

from dialogue_lab.context.manager import ContextManager
from dialogue_lab.context.system_prompt import SystemPrompts
from dialogue_lab.runtime.events import Submit
from dialogue_lab.runtime.scheduler import Scheduler
from dialogue_lab.runtime.tools import Tools
from dialogue_lab.storage.character_store import CharacterStore


@pytest.mark.asyncio
async def test_state_tool_commits_then_continues_reply_and_survives_reopening(
    session_service, tmp_path
):
    (tmp_path / "default.md").write_text("Be brief.", encoding="utf-8")
    adapter = ScriptedAdapter(
        [
            [
                ToolCall(
                    "state-1",
                    "update_session_state",
                    arguments={
                        "activity": "英语练习",
                        "instructions": ["使用英文", "只纠正明显错误"],
                    },
                )
            ],
            ["Let's talk."],
            [
                ToolCall(
                    "state-2",
                    "update_session_state",
                    arguments={
                        "instructions": ["使用英文", "不主动纠错"],
                    },
                )
            ],
            ["Sure."],
        ]
    )
    models, model = make_models(adapter)
    sid = int((await session_service.create("Practice"))["session_id"])
    events = []

    async def emit(event):
        events.append(event)

    scheduler = Scheduler(
        sid,
        session_service,
        ContextManager(session_service, models, model, SystemPrompts(tmp_path)),
        models,
        model,
        emit,
    )
    try:
        await scheduler.submit(Submit(uuid4(), "接下来练英语，只纠正明显错误", "default"))
        await asyncio.wait_for(scheduler.wait_idle(), 5)
        opened = await session_service.open(sid)
        assert opened["messages"][-1]["message_json"]["content"][0] == {
            "type": "text",
            "text": "Let's talk.",
            "metadata": {},
        }
        assert opened["session_state"] == {
            "activity": "英语练习",
            "instructions": ["使用英文", "只纠正明显错误"],
        }
        transcript = json.dumps(
            [vars(m) for m in adapter.inputs[1].messages], default=vars, ensure_ascii=False
        )
        assert "英语练习" in transcript
        assert "state-1" in transcript
        assert len(opened["messages"]) == 2  # 内部工具消息不显示在聊天中。
        await scheduler.submit(Submit(uuid4(), "不纠错了，继续英文", "default"))
        await asyncio.wait_for(scheduler.wait_idle(), 5)
        assert (await session_service.open(sid))["session_state"] == {
            "activity": "英语练习",
            "instructions": ["使用英文", "不主动纠错"],
        }
        fresh = await session_service.create("New")
        assert fresh["session_state"] == {"activity": None, "instructions": []}
        assert not any(e["type"] == "error" for e in events)
    finally:
        await scheduler.close()
        await models.aclose()


@pytest.mark.asyncio
async def test_tool_limit_records_unexecuted_call_before_next_turn(session_service, tmp_path):
    (tmp_path / "default.md").write_text("Be brief.", encoding="utf-8")
    adapter = ScriptedAdapter(
        [
            [ToolCall("one", "update_session_state", arguments={"activity": "English"})],
            [ToolCall("two", "update_session_state", arguments={"activity": "Not committed"})],
            ["Recovered"],
        ]
    )
    models, model = make_models(adapter)
    sid = int((await session_service.create("Limit"))["session_id"])
    events = []

    async def emit(event):
        events.append(event)

    scheduler = Scheduler(
        sid,
        session_service,
        ContextManager(session_service, models, model, SystemPrompts(tmp_path)),
        models,
        model,
        emit,
        max_tool_rounds=1,
    )
    try:
        await scheduler.submit(Submit(uuid4(), "Start", "default"))
        await asyncio.wait_for(scheduler.wait_idle(), 5)
        assert any(e.get("code") == "TOOL_LIMIT" for e in events)
        assert (await session_service.open(sid))["session_state"]["activity"] == "English"
        await scheduler.submit(Submit(uuid4(), "Continue", "default"))
        await asyncio.wait_for(scheduler.wait_idle(), 5)
        results = [m for m in adapter.inputs[-1].messages if m.role == "tool_result"]
        assert {m.tool_call_id for m in results} == {"one", "two"}
        assert next(m for m in results if m.tool_call_id == "two").is_error
    finally:
        await scheduler.close()
        await models.aclose()


@pytest.mark.asyncio
async def test_saved_core_memory_reaches_same_character_but_not_another(
    session_service, database, tmp_path
):
    (tmp_path / "default.md").write_text("Stay in character.", encoding="utf-8")
    characters = await CharacterStore(database).list()
    first, second = [r["character_id"] for r in characters[:2]]
    adapter = ScriptedAdapter(
        [
            [
                ToolCall(
                    "remember",
                    "save_memory",
                    arguments={
                        "content": "喜欢无糖乌龙茶",
                        "is_core": True,
                    },
                )
            ],
            ["记住了。"],
            ["欢迎回来。"],
            ["你好。"],
        ]
    )
    models, model = make_models(adapter)

    async def emit(event):
        pass

    async def chat(character_id, text):
        sid = int((await session_service.create("Chat", character_id))["session_id"])
        scheduler = Scheduler(
            sid,
            session_service,
            ContextManager(session_service, models, model, SystemPrompts(tmp_path)),
            models,
            model,
            emit,
        )
        try:
            await scheduler.submit(Submit(uuid4(), text, "default"))
            await asyncio.wait_for(scheduler.wait_idle(), 5)
        finally:
            await scheduler.close()
        return sid

    try:
        await chat(first, "记住我喜欢无糖乌龙茶")
        await chat(first, "回来啦")
        same = json.dumps(
            [vars(m) for m in adapter.inputs[-1].messages], default=vars, ensure_ascii=False
        )
        assert "喜欢无糖乌龙茶" in same
        await chat(second, "你好")
        other = json.dumps(
            [vars(m) for m in adapter.inputs[-1].messages], default=vars, ensure_ascii=False
        )
        assert "无糖乌龙茶" not in other
    finally:
        await models.aclose()


@pytest.mark.asyncio
async def test_cancel_before_tool_commit_rolls_back_state_and_result(session_service, database):
    sid = int((await session_service.create("Atomic state"))["session_id"])
    request = uuid4()
    await session_service.submit(sid, request, "Use English")
    call = ToolCall("state", "update_session_state", arguments={"activity": "English"})
    await session_service.save_assistant(
        sid,
        request,
        AssistantMessage(
            "test",
            "dialogue",
            "test",
            content=[call],
            stop_reason="tool_use",
        ),
    )
    controller = AbortController()

    def cancel_after_result_insert(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO session_messages") and "tool_result" in parameters:
            controller.abort()

    event.listen(database.engine.sync_engine, "after_cursor_execute", cancel_after_result_insert)
    try:
        with pytest.raises(asyncio.CancelledError):
            await Tools(session_service).execute(sid, request, 1, call, controller.signal)
    finally:
        event.remove(
            database.engine.sync_engine, "after_cursor_execute", cancel_after_result_insert
        )
    assert (await session_service.open(sid))["session_state"] == {
        "activity": None,
        "instructions": [],
    }
    assert not any(row["message_kind"] == "tool_result" for row in await session_service.path(sid))
    # 同一调用重试可以提交；再次提交只读取原结果。
    tools = Tools(session_service)
    result = await tools.execute(sid, request, 1, call)
    assert await tools.execute(sid, request, 1, call) == result
    assert (await session_service.open(sid))["session_state"]["activity"] == "English"
    assert (
        len(
            [row for row in await session_service.path(sid) if row["message_kind"] == "tool_result"]
        )
        == 1
    )
