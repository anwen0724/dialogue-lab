"""通过工具入口和 Context 验证记忆；数据库与业务实现均真实执行。"""

import asyncio
import json
from uuid import uuid4

import pytest
from ai import AssistantMessage, SimpleOptions, TextContent, ToolCall, message_to_dict
from model_provider import ScriptedAdapter
from model_provider import test_models as make_models

from dialogue_lab.context.compaction import CompactionSettings
from dialogue_lab.context.manager import ContextManager
from dialogue_lab.context.system_prompt import SystemPrompts
from dialogue_lab.runtime.events import Submit
from dialogue_lab.runtime.scheduler import Scheduler
from dialogue_lab.runtime.tools import Tools
from dialogue_lab.storage.character_store import CharacterStore
from dialogue_lab.storage.compaction_store import CompactionStore


async def invoke(sessions, sid, name, arguments, text="明确的用户请求"):
    request = uuid4()
    await sessions.submit(sid, request, text)
    call = ToolCall(str(uuid4()), name, arguments=arguments)
    await sessions.save_assistant(
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
    result = await Tools(sessions).execute(sid, request, 1, call)
    return json.loads(result["content"]), result["is_error"]


@pytest.mark.asyncio
async def test_memory_search_returns_sources_and_history_is_character_scoped(
    session_service, database
):
    characters = await CharacterStore(database).list()
    first, other = [r["character_id"] for r in characters[:2]]
    sid = int((await session_service.create("Old", first))["session_id"])
    saved, error = await invoke(
        session_service,
        sid,
        "save_memory",
        {
            "content": "下周面试后端岗位",
        },
        "记住我下周面试后端岗位",
    )
    assert not error
    new = int((await session_service.create("New", first))["session_id"])
    found, error = await invoke(session_service, new, "search_memory", {"query": "面试"})
    assert not error
    assert found["matches"][0]["content"] == "下周面试后端岗位"
    assert found["matches"][0]["id"] == saved["id"]
    source = found["matches"][0]["sources"][0]
    history, error = await invoke(
        session_service,
        new,
        "read_history",
        {
            "session_id": source["session_id"],
            "message_ids": [source["message_id"]],
        },
    )
    assert not error
    assert "记住我下周面试后端岗位" in json.dumps(history, ensure_ascii=False)
    foreign = int((await session_service.create("Other", other))["session_id"])
    denied, error = await invoke(
        session_service,
        foreign,
        "read_history",
        {
            "session_id": source["session_id"],
            "message_ids": [source["message_id"]],
        },
    )
    assert error
    assert denied["code"] == "HISTORY_SCOPE"
    empty, error = await invoke(session_service, foreign, "search_memory", {"query": "面试"})
    assert not error
    assert empty["matches"] == []


@pytest.mark.asyncio
async def test_invalid_state_tool_patch_keeps_the_saved_agreement(session_service):
    sid = int((await session_service.create("State"))["session_id"])
    original, error = await invoke(
        session_service, sid, "update_session_state", {"activity": "English", "instructions": []}
    )
    assert not error
    rejected, error = await invoke(
        session_service, sid, "update_session_state", {"instructions": "not-a-list"}
    )
    assert error
    assert rejected["code"] == "INVALID_TOOL_ARGUMENTS"
    assert (await session_service.open(sid))["session_state"] == original


@pytest.mark.asyncio
async def test_empty_time_bound_is_not_treated_as_an_unfiltered_search(session_service, database):
    character = (await CharacterStore(database).list())[0]["character_id"]
    sid = int((await session_service.create("Search", character))["session_id"])
    result, error = await invoke(session_service, sid, "search_memory", {"query": "", "after": ""})
    assert error
    assert result["code"] == "INVALID_TIME_RANGE"


@pytest.mark.asyncio
async def test_forgetting_memory_keeps_unrelated_user_input_available(
    session_service, database, tmp_path
):
    (tmp_path / "default.md").write_text("Brief", encoding="utf-8")
    character = (await CharacterStore(database).list())[0]["character_id"]
    sid = int((await session_service.create("History", character))["session_id"])
    old, error = await invoke(
        session_service, sid, "save_memory", {"content": "OLD-tea", "is_core": True}
    )
    assert not error
    request = uuid4()
    user, _ = await session_service.submit(sid, request, "周末喜欢骑车")
    await session_service.save_assistant(
        sid,
        request,
        AssistantMessage("test", "dialogue", "test", content=[TextContent("Ride, then OLD-tea.")]),
        memory_refs={str(old["id"]): old["revision"]},
    )
    _, error = await invoke(session_service, sid, "forget_memory", {"memory_id": old["id"]})
    assert not error
    models, model = make_models(ScriptedAdapter([]))
    try:
        manager = ContextManager(session_service, models, model, SystemPrompts(tmp_path))
        context = await manager.to_context(await manager.build(sid, "default"))
        actual = json.dumps([message_to_dict(m) for m in context.messages], ensure_ascii=False)
        assert "OLD-tea" not in actual
        assert "周末喜欢骑车" in actual
        source = {"session_id": sid, "message_ids": [int(user["message_id"])]}
        history, error = await invoke(session_service, sid, "read_history", source)
        assert not error
        assert "周末喜欢骑车" in json.dumps(history, ensure_ascii=False)
        saved, error = await invoke(
            session_service,
            sid,
            "save_memory",
            {
                "content": "周末喜欢骑车",
                "source_message_ids": source["message_ids"],
            },
        )
        assert not error, saved
        assert saved["content"] == "周末喜欢骑车"
    finally:
        await models.aclose()


@pytest.mark.asyncio
async def test_context_does_not_preload_memory_already_in_tool_result(
    session_service, database, tmp_path
):
    (tmp_path / "default.md").write_text("Brief", encoding="utf-8")
    character = (await CharacterStore(database).list())[0]["character_id"]
    sid = int((await session_service.create("No duplicate", character))["session_id"])
    saved, error = await invoke(
        session_service,
        sid,
        "save_memory",
        {
            "content": "喜欢乌龙茶",
            "is_core": True,
        },
    )
    assert not error
    models, model = make_models(ScriptedAdapter([]))
    try:
        manager = ContextManager(session_service, models, model, SystemPrompts(tmp_path))
        prepared = await manager.build(sid, "default")
        assert saved["id"] not in [memory.id for memory in prepared.memories]
        context = await manager.to_context(prepared)
        assert any(m.role == "tool_result" and "喜欢乌龙茶" in m.content for m in context.messages)
    finally:
        await models.aclose()


@pytest.mark.asyncio
async def test_auto_compaction_does_not_reuse_memory_forgotten_while_summarizing(
    session_service, database, tmp_path
):
    (tmp_path / "default.md").write_text("Brief", encoding="utf-8")
    character = (await CharacterStore(database).list())[0]["character_id"]
    sid = int((await session_service.create("History", character))["session_id"])
    saved, error = await invoke(
        session_service, sid, "save_memory", {"content": "OLD-violet-tea", "is_core": True}
    )
    assert not error
    await session_service.submit(sid, uuid4(), "Earlier conversation " * 400)
    summarizing, proceed = asyncio.Event(), asyncio.Event()

    class PausedSummary(ScriptedAdapter):
        async def stream_simple(self, model, context, auth, options):
            if not self.inputs:
                summarizing.set()
                await proceed.wait()
            async for event in super().stream_simple(model, context, auth, options):
                yield event

    adapter = PausedSummary([["OLD-violet-tea"], ["Hello"], ["Recent conversation"]])
    models, model = make_models(adapter)
    manager = ContextManager(
        session_service,
        models,
        model,
        SystemPrompts(tmp_path),
        CompactionStore(database),
        CompactionSettings(reserve_tokens=99000, keep_recent_tokens=10),
    )
    events = []

    async def emit(event):
        events.append(event)

    scheduler = Scheduler(
        sid,
        session_service,
        manager,
        models,
        model,
        emit,
        options=SimpleOptions(max_output_tokens=512),
    )
    try:
        await scheduler.submit(Submit(uuid4(), "Continue", "default"))
        await asyncio.wait_for(summarizing.wait(), 5)
        other = int((await session_service.create("Forget", character))["session_id"])
        _, error = await invoke(session_service, other, "forget_memory", {"memory_id": saved["id"]})
        assert not error
        proceed.set()
        await asyncio.wait_for(scheduler.wait_idle(), 5)
        assert not [event for event in events if event["type"] == "error"]
        actual = json.dumps([message_to_dict(m) for m in adapter.inputs[1].messages])
        assert "OLD-violet-tea" not in actual
    finally:
        proceed.set()
        await scheduler.close()
        await models.aclose()


@pytest.mark.asyncio
async def test_history_can_be_compacted_again_after_memory_is_forgotten(
    session_service, database, tmp_path
):
    (tmp_path / "default.md").write_text("Brief", encoding="utf-8")
    character = (await CharacterStore(database).list())[0]["character_id"]
    sid = int((await session_service.create("History", character))["session_id"])
    saved, error = await invoke(session_service, sid, "save_memory", {"content": "OLD-violet-tea"})
    assert not error
    await invoke(session_service, sid, "update_session_state", {"instructions": ["Use English"]})
    await session_service.submit(sid, uuid4(), "Recent conversation " * 200)
    models, model = make_models(ScriptedAdapter([["OLD-violet-tea"], ["Preference withdrawn."]]))
    manager = ContextManager(
        session_service,
        models,
        model,
        SystemPrompts(tmp_path),
        CompactionStore(database),
        CompactionSettings(keep_recent_tokens=100),
    )
    try:
        assert await manager.compact(sid, await manager.build(sid, "default"), SimpleOptions())
        other = int((await session_service.create("Forget", character))["session_id"])
        _, error = await invoke(session_service, other, "forget_memory", {"memory_id": saved["id"]})
        assert not error
        assert await manager.compact(sid, await manager.build(sid, "default"), SimpleOptions())
        context = await manager.to_context(await manager.build(sid, "default"))
        encoded = json.dumps([message_to_dict(m) for m in context.messages])
        assert "OLD-violet-tea" not in encoded
        assert "Preference withdrawn." in encoded
        assert "Use English" in encoded
    finally:
        await models.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["correct", "forget"])
async def test_changed_memory_is_removed_from_raw_projection_tools_and_summary(
    session_service, database, tmp_path, change
):
    (tmp_path / "default.md").write_text("Stay in character.", encoding="utf-8")
    character = (await CharacterStore(database).list())[0]["character_id"]
    sid = int((await session_service.create("Memory", character))["session_id"])
    saved, error = await invoke(
        session_service,
        sid,
        "save_memory",
        {
            "content": "OLD-violet-tea",
            "is_core": True,
        },
        "记住 OLD-violet-tea",
    )
    assert not error
    await invoke(session_service, sid, "search_memory", {"query": "OLD-violet-tea"})
    await session_service.submit(sid, uuid4(), "最新话题 " * 200)
    models, model = make_models(ScriptedAdapter([["The user likes OLD-violet-tea."]]))
    manager = ContextManager(
        session_service,
        models,
        model,
        SystemPrompts(tmp_path),
        CompactionStore(database),
        CompactionSettings(keep_recent_tokens=100),
    )
    try:
        assert await manager.compact(sid, await manager.build(sid, "default"), SimpleOptions())
        if change == "correct":
            result, error = await invoke(
                session_service,
                sid,
                "save_memory",
                {
                    "memory_id": saved["id"],
                    "content": "NEW-green-tea",
                    "is_core": True,
                },
                "改成 NEW-green-tea",
            )
        else:
            result, error = await invoke(
                session_service,
                sid,
                "forget_memory",
                {
                    "memory_id": saved["id"],
                },
                "忘掉之前那个偏好",
            )
        assert not error, result
        context = await manager.to_context(await manager.build(sid, "default"))
        encoded = json.dumps([message_to_dict(m) for m in context.messages], ensure_ascii=False)
        assert "OLD-violet-tea" not in encoded
        assert ("NEW-green-tea" in encoded) == (change == "correct")
        assert "OLD-violet-tea" in json.dumps(await session_service.open(sid), ensure_ascii=False)
        source = saved["sources"][0]
        reread, error = await invoke(
            session_service,
            sid,
            "read_history",
            {
                "session_id": source["session_id"],
                "message_ids": [source["message_id"]],
            },
        )
        assert not error
        assert "OLD-violet-tea" not in json.dumps(reread, ensure_ascii=False)
        rejected, error = await invoke(
            session_service,
            sid,
            "save_memory",
            {
                "content": "OLD-violet-tea",
                "source_message_ids": [source["message_id"]],
            },
        )
        assert error
        assert rejected["code"] == "MEMORY_SOURCE_WITHDRAWN"
    finally:
        await models.aclose()
