"""显式启用的真实模型和语音检查；使用合成对话和隔离数据库。"""

import asyncio
import os
from uuid import uuid4

import pytest
from ai import SimpleOptions, ToolCall
from model_provider import ScriptedAdapter
from model_provider import test_models as make_models

from dialogue_lab.bootstrap import Services
from dialogue_lab.config import Settings
from dialogue_lab.context.manager import ContextManager
from dialogue_lab.context.system_prompt import SystemPrompts
from dialogue_lab.runtime.events import Submit
from dialogue_lab.runtime.scheduler import Scheduler

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("DIALOGUE_LAB_LIVE_TESTS") != "1",
        reason="真实模型调用需显式设置 DIALOGUE_LAB_LIVE_TESTS=1",
    ),
]


async def test_live_model_distinguishes_one_off_request_and_persistent_agreement(
    database, tmp_path
):
    services = Services(Settings())
    (tmp_path / "default.md").write_text(
        "你是温柔直接的对话伙伴小夏。保持简短自然。默认中文交流。",
        encoding="utf-8",
    )
    selected = services.application_settings.current.dialogue
    model = services.models.get_model(selected.provider_id, selected.model_id)
    sid = int((await services.sessions.create("Synthetic live acceptance"))["session_id"])
    events = []

    async def emit(event):
        events.append(event)

    scheduler = Scheduler(
        sid,
        services.sessions,
        ContextManager(services.sessions, services.models, model, SystemPrompts(tmp_path)),
        services.models,
        model,
        emit,
        options=SimpleOptions(max_output_tokens=512, timeout=45),
        tools=services.tools,
    )
    try:
        for text, persistent in [
            ("只翻译这句话：今天天气不错。不改变后续交流方式。", False),
            ("接下来陪我用英语聊天，只纠正影响理解的错误。", True),
            ("练习结束，清除刚才的英语交流和纠错约定，恢复平时聊天。", False),
        ]:
            await scheduler.submit(Submit(uuid4(), text, "default"))
            await asyncio.wait_for(scheduler.wait_idle(), 120)
            assert not [e for e in events if e["type"] == "error"]
            opened = await services.sessions.open(sid)
            state = opened["session_state"]
            if persistent:
                assert state["activity"] and state["instructions"]
            else:
                assert state == {"activity": None, "instructions": []}
            assert opened["messages"][-1]["message_kind"] == "assistant_message"
            assert any(b.get("text") for b in opened["messages"][-1]["message_json"]["content"])
    finally:
        await scheduler.close()
        await services.close()


async def test_live_model_saves_recalls_and_forgets_a_synthetic_preference(database, tmp_path):
    services = Services(Settings())
    (tmp_path / "default.md").write_text(
        "你是对话伙伴小夏。默认中文。简短自然地回应，不编造共同经历。",
        encoding="utf-8",
    )
    character = await services.characters.store.create(
        {
            "name": "Synthetic memory",
            "category": "test",
            "character_name": "小夏",
            "prompt_key": "live-" + uuid4().hex,
        }
    )
    selected = services.application_settings.current.dialogue
    model = services.models.get_model(selected.provider_id, selected.model_id)
    errors = []

    async def emit(event):
        if event["type"] == "error":
            errors.append(event)

    async def send(sid, text):
        scheduler = Scheduler(
            sid,
            services.sessions,
            ContextManager(services.sessions, services.models, model, SystemPrompts(tmp_path)),
            services.models,
            model,
            emit,
            tools=services.tools,
            options=SimpleOptions(max_output_tokens=512, timeout=45),
        )
        try:
            await scheduler.submit(Submit(uuid4(), text, "default"))
            await asyncio.wait_for(scheduler.wait_idle(), 120)
            assert not errors
        finally:
            await scheduler.close()

    try:
        sid = int(
            (await services.sessions.create("First", character["character_id"]))["session_id"]
        )
        await send(sid, "请长期记住我的饮品偏好：无糖乌龙茶。作为每次交流都知道的核心记忆保存。")
        core = await services.memory.core(sid)
        assert any("无糖乌龙茶" in m.content for m in core)
        second = int(
            (await services.sessions.create("Return", character["character_id"]))["session_id"]
        )
        await send(second, "我喜欢喝什么？")
        reply = (await services.sessions.open(second))["messages"][-1]["message_json"]["content"]
        assert "无糖乌龙茶" in "".join(b.get("text", "") for b in reply)
        await send(second, "请删除刚才那条饮品偏好记忆，以后不要再作为我的偏好使用。")
        assert not await services.memory.core(second)
    finally:
        await services.close()


@pytest.mark.skipif(
    os.environ.get("DIALOGUE_LAB_LIVE_SPEECH") != "1",
    reason="真实语音调用需显式设置 DIALOGUE_LAB_LIVE_SPEECH=1",
)
async def test_live_speech_after_tool_call_delivers_audio_and_timing(database, tmp_path):
    services = Services(Settings())
    (tmp_path / "default.md").write_text("Be brief.", encoding="utf-8")
    sid = int((await services.sessions.create("Synthetic speech"))["session_id"])
    speech = await services.reply_settings(sid)
    assert speech.synthesis_factory is not None, speech.speech_notice
    adapter = ScriptedAdapter(
        [
            [ToolCall("state", "update_session_state", arguments={"activity": "English"})],
            ["Hello. Let's talk."],
        ]
    )
    models, model = make_models(adapter)
    events = []

    async def emit(event):
        events.append(event)

    scheduler = Scheduler(
        sid,
        services.sessions,
        ContextManager(services.sessions, models, model, SystemPrompts(tmp_path)),
        models,
        model,
        emit,
        synthesis_factory=speech.synthesis_factory,
    )
    try:
        await scheduler.submit(Submit(uuid4(), "Start English", "default"))
        await asyncio.wait_for(scheduler.wait_idle(), 90)
        assert not [e for e in events if e["type"] == "error"]
        assert sum(len(e["data"]) for e in events if e["type"] == "audio") > 0
        assert any(e["type"] == "text_timing" for e in events)
        assert any(e["type"] == "audio_finished" for e in events)
    finally:
        await scheduler.close()
        await models.aclose()
        await services.close()
