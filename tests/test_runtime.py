"""真实会话、上下文与调度组合；替身只位于模型供应商边界。"""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
import speechio
from ai import SimpleOptions, TextContent, UserMessage
from model_provider import ScriptedAdapter
from model_provider import test_models as make_models

from dialogue_lab.context.compaction import CompactionSettings
from dialogue_lab.context.manager import ContextManager
from dialogue_lab.context.system_prompt import SystemPrompts
from dialogue_lab.runtime.events import Submit
from dialogue_lab.runtime.scheduler import Scheduler
from dialogue_lab.sessions.types import SessionError
from dialogue_lab.storage.compaction_store import CompactionStore
from dialogue_lab.voice.synthesis import Synthesis


@pytest.mark.asyncio
async def test_two_turns_share_persisted_context_without_duplicate_input(session_service, tmp_path):
    (tmp_path / "default.md").write_text("Be brief.", encoding="utf-8")
    adapter = ScriptedAdapter([["Hello"], ["Yes, I remember."]])
    models, model = make_models(adapter)
    session_id = int((await session_service.create("Practice"))["session_id"])
    manager = ContextManager(session_service, models, model, SystemPrompts(tmp_path))
    events = []

    async def emit(event):
        events.append(event)

    scheduler = Scheduler(session_id, session_service, manager, models, model, emit)
    try:
        first = Submit(uuid4(), "My name is Lin", "default")
        await scheduler.submit(first)
        await scheduler.wait_idle()
        await scheduler.submit(first)
        await scheduler.submit(Submit(uuid4(), "Remember me?", "default"))
        await scheduler.wait_idle()
        assert len(adapter.inputs) == 2
        second = adapter.inputs[1].messages
        assert second[1] == UserMessage([TextContent("My name is Lin")])
        assert second[2].content[0].text == "Hello"
        assert second[3] == UserMessage([TextContent("Remember me?")])
        assert len((await session_service.open(session_id))["messages"]) == 4
        assert any(event["type"] == "text_delta" for event in events)
    finally:
        await scheduler.close()
        await models.aclose()


@pytest.mark.asyncio
async def test_new_input_cancels_old_reply_and_saves_partial_before_next_input(
    session_service,
    tmp_path,
):
    (tmp_path / "default.md").write_text("Be brief.", encoding="utf-8")
    started = asyncio.Event()

    class PausingAdapter(ScriptedAdapter):
        async def stream_simple(self, model, context, auth, options):
            first = not self.inputs
            async for event in super().stream_simple(model, context, auth, options):
                if first and event.type == "done":
                    started.set()
                    await asyncio.Event().wait()
                yield event

    adapter = PausingAdapter([["Partial"], ["New answer"]])
    models, model = make_models(adapter)
    session_id = int((await session_service.create("Practice"))["session_id"])
    manager = ContextManager(session_service, models, model, SystemPrompts(tmp_path))
    events = []

    async def emit(event):
        events.append(event)

    scheduler = Scheduler(session_id, session_service, manager, models, model, emit)
    try:
        first = Submit(uuid4(), "First", "default")
        await scheduler.submit(first)
        await asyncio.wait_for(started.wait(), 2)
        assert len((await session_service.open(session_id))["messages"]) == 1
        await scheduler.submit(Submit(uuid4(), "Second", "default"))
        await asyncio.wait_for(scheduler.wait_idle(), 2)
        messages = (await session_service.open(session_id))["messages"]
        assert messages[1]["message_json"]["status"] == "cancelled"
        assert messages[1]["message_json"]["content"][0]["text"] == "Partial"
        assert messages[2]["message_json"]["display_content"][0]["text"] == "Second"
        assert messages[3]["message_json"]["content"][0]["text"] == "New answer"
    finally:
        await scheduler.close()
        await models.aclose()


@pytest.mark.asyncio
async def test_auto_compaction_queues_new_input_without_changing_path(
    session_service,
    database,
    tmp_path,
):
    (tmp_path / "default.md").write_text("Brief", encoding="utf-8")
    summarizing, release, queued = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class PausingSummaryAdapter(ScriptedAdapter):
        async def stream_simple(self, model, context, auth, options):
            if len(self.inputs) == 1:
                summarizing.set()
                await release.wait()
            async for event in super().stream_simple(model, context, auth, options):
                yield event

    adapter = PausingSummaryAdapter([["b" * 1000], ["s"], ["OK"]])
    models, model = make_models(adapter)
    session_id = int((await session_service.create("Practice"))["session_id"])
    manager = ContextManager(
        session_service,
        models,
        model,
        SystemPrompts(tmp_path),
        CompactionStore(database),
        CompactionSettings(reserve_tokens=99499, keep_recent_tokens=250),
    )

    async def emit(event):
        if event["type"] == "input_queued":
            queued.set()

    scheduler = Scheduler(
        session_id,
        session_service,
        manager,
        models,
        model,
        emit,
        options=SimpleOptions(max_output_tokens=1024),
    )
    pending = None
    try:
        await scheduler.submit(Submit(uuid4(), "a" * 1000, "default"))
        await asyncio.wait_for(summarizing.wait(), 2)
        before = (await session_service.open(session_id))["messages"]
        pending = asyncio.create_task(scheduler.submit(Submit(uuid4(), "Next", "default")))
        await asyncio.wait_for(queued.wait(), 2)
        assert (await session_service.open(session_id))["messages"] == before
        release.set()
        await asyncio.wait_for(pending, 2)
        await asyncio.wait_for(scheduler.wait_idle(), 2)
        saved = (await session_service.open(session_id))["messages"]
        assert len(saved) == 4
        assert saved[-1]["message_json"]["content"][0]["text"] == "OK"
    finally:
        release.set()
        await scheduler.close()
        if pending:
            await asyncio.gather(pending, return_exceptions=True)
        await models.aclose()


@pytest.mark.asyncio
async def test_tts_failure_does_not_lose_or_fail_generated_text(
    session_service, tmp_path, monkeypatch
):
    (tmp_path / "default.md").write_text("Be brief.", encoding="utf-8")

    def unavailable(config):
        raise RuntimeError("TTS unavailable")

    monkeypatch.setattr(speechio, "Synthesizer", unavailable)
    models, model = make_models(ScriptedAdapter([["Saved text"]]))
    session_id = int((await session_service.create("Practice"))["session_id"])
    manager = ContextManager(session_service, models, model, SystemPrompts(tmp_path))
    events = []

    async def emit(event):
        events.append(event)

    scheduler = Scheduler(
        session_id,
        session_service,
        manager,
        models,
        model,
        emit,
        synthesis_factory=lambda: Synthesis(api_key="test", model="test", voice="test"),
    )
    try:
        await scheduler.submit(Submit(uuid4(), "Hello", "default"))
        await asyncio.wait_for(scheduler.wait_idle(), 3)
        messages = (await session_service.open(session_id))["messages"]
        assert messages[-1]["message_json"]["status"] == "completed"
        assert messages[-1]["message_json"]["content"][0]["text"] == "Saved text"
        assert any(event.get("code") == "TTS_FAILED" for event in events)
    finally:
        await scheduler.close()
        await models.aclose()


@pytest.mark.asyncio
async def test_manual_compaction_rejects_input_until_finished(session_service, database, tmp_path):
    (tmp_path / "default.md").write_text("Brief", encoding="utf-8")
    started, release = asyncio.Event(), asyncio.Event()

    class PausingAdapter(ScriptedAdapter):
        async def stream_simple(self, model, context, auth, options):
            started.set()
            await release.wait()
            async for event in super().stream_simple(model, context, auth, options):
                yield event

    models, model = make_models(PausingAdapter([["summary"]]))
    session_id = int((await session_service.create("Practice"))["session_id"])
    for text in ("a" * 40, "b" * 40):
        await session_service.submit(session_id, uuid4(), text)
    manager = ContextManager(
        session_service,
        models,
        model,
        SystemPrompts(tmp_path),
        CompactionStore(database),
        CompactionSettings(keep_recent_tokens=10),
    )

    async def emit(event):
        pass

    scheduler = Scheduler(session_id, session_service, manager, models, model, emit)
    pending = asyncio.create_task(scheduler.compact("default"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(SessionError) as caught:
            await scheduler.submit(Submit(uuid4(), "Next", "default"))
        assert caught.value.code == "COMPACTION_BUSY"
        release.set()
        assert await asyncio.wait_for(pending, 2) is True
    finally:
        release.set()
        await scheduler.close()
        await asyncio.gather(pending, return_exceptions=True)
        await models.aclose()


@pytest.mark.asyncio
async def test_input_exceeding_window_is_not_silently_truncated_or_sent(
    session_service,
    database,
    tmp_path,
):
    (tmp_path / "default.md").write_text("Brief", encoding="utf-8")
    adapter = ScriptedAdapter([["should not run"]])
    models, model = make_models(adapter)
    model = replace(model, context_window=50)
    session_id = int((await session_service.create("Practice"))["session_id"])
    manager = ContextManager(
        session_service,
        models,
        model,
        SystemPrompts(tmp_path),
        CompactionStore(database),
        CompactionSettings(reserve_tokens=10, keep_recent_tokens=20),
    )
    events = []

    async def emit(event):
        events.append(event)

    scheduler = Scheduler(
        session_id,
        session_service,
        manager,
        models,
        model,
        emit,
        options=SimpleOptions(max_output_tokens=10),
    )
    try:
        await scheduler.submit(Submit(uuid4(), "a" * 400, "default"))
        await asyncio.wait_for(scheduler.wait_idle(), 2)
        assert adapter.inputs == []
        assert any(event.get("code") == "CONTEXT_TOO_LARGE" for event in events)
        assert len((await session_service.open(session_id))["messages"]) == 1
    finally:
        await scheduler.close()
        await models.aclose()
