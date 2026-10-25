"""验证上下文的公开输入输出，不替换内容组织逻辑。"""

from uuid import uuid4

import pytest
from ai import AssistantMessage, SimpleOptions, SystemMessage, TextContent, Usage, UserMessage
from model_provider import ScriptedAdapter
from model_provider import test_models as make_models

from dialogue_lab.context.compaction import (
    CompactionSettings,
    estimate_context_tokens,
    find_cut_point,
    summarize,
)
from dialogue_lab.context.manager import ContextManager
from dialogue_lab.context.messages import CompactionSummary, convert_to_llm
from dialogue_lab.context.system_prompt import SystemPrompts
from dialogue_lab.storage.compaction_store import CompactionStore


def test_prompt_document_changes_apply_to_next_load(tmp_path):
    document = tmp_path / "english.md"
    document.write_text("You are an English tutor.", encoding="utf-8")
    prompts = SystemPrompts(tmp_path)
    first = prompts.load("english")
    document.write_text("Keep every answer brief.", encoding="utf-8")
    second = prompts.load("english")
    assert first.content == "You are an English tutor."
    assert second.content == "Keep every answer brief."


@pytest.mark.asyncio
async def test_context_loads_current_instructions_and_current_input_once(session_service, tmp_path):
    (tmp_path / "english.md").write_text("Be an English tutor.", encoding="utf-8")
    models, model = make_models(ScriptedAdapter([]))
    session_id = int((await session_service.create("Practice"))["session_id"])
    await session_service.submit(session_id, uuid4(), "Hello")
    other = int((await session_service.create("Other"))["session_id"])
    await session_service.submit(other, uuid4(), "Do not include me")
    manager = ContextManager(session_service, models, model, SystemPrompts(tmp_path))
    try:
        prepared = await manager.build(session_id, "english")
        assert prepared.messages == [
            SystemMessage(content="Be an English tutor."),
            UserMessage(content=[TextContent("Hello")]),
        ]
        assert len((await session_service.open(session_id))["messages"]) == 1
    finally:
        await models.aclose()


@pytest.mark.asyncio
async def test_compaction_changes_model_input_but_keeps_original_chat(
    session_service,
    database,
    tmp_path,
):
    (tmp_path / "english.md").write_text("Be brief.", encoding="utf-8")
    models, model = make_models(ScriptedAdapter([["Earlier facts"]]))
    session_id = int((await session_service.create("Practice"))["session_id"])
    for text in ("a" * 40, "b" * 40, "c" * 16):
        await session_service.submit(session_id, uuid4(), text)
    original = (await session_service.open(session_id))["messages"]
    manager = ContextManager(
        session_service,
        models,
        model,
        SystemPrompts(tmp_path),
        CompactionStore(database),
        CompactionSettings(keep_recent_tokens=4),
    )
    try:
        prepared = await manager.build(session_id, "english")
        assert await manager.compact(session_id, prepared, SimpleOptions()) is True
        compacted = await manager.build(session_id, "english")
        assert compacted.messages == [
            SystemMessage(content="Be brief."),
            CompactionSummary("Earlier facts"),
            UserMessage([TextContent("c" * 16)]),
        ]
        assert (await session_service.open(session_id))["messages"] == original
    finally:
        await models.aclose()


def test_summary_is_converted_only_in_model_input():
    summary = CompactionSummary("User is preparing for an interview.")
    messages = [SystemMessage(content="Be brief."), summary, UserMessage("Continue")]
    model_input = convert_to_llm(messages)
    assert messages[1] is summary
    assert model_input.messages[0] == messages[0]
    assert model_input.messages[1] == UserMessage(
        "The conversation history before this point was compacted into the following summary:"
        "\n\n<summary>\nUser is preparing for an interview.\n</summary>"
    )
    assert model_input.messages[2] == UserMessage("Continue")


def test_compaction_keeps_recent_token_budget_and_can_split_a_turn():
    messages = [
        UserMessage("a" * 40),
        AssistantMessage("test", "test", "test", content=[TextContent("b" * 40)]),
        UserMessage("c" * 16),
    ]
    assert find_cut_point(messages, keep_recent_tokens=12) == 1
    assert find_cut_point(messages, keep_recent_tokens=100) == 0


def test_budget_uses_valid_usage_and_reestimates_after_context_change():
    messages = [
        SystemMessage(content="s" * 40),
        UserMessage("u" * 40),
        AssistantMessage(
            "test", "test", "test", content=[TextContent("a" * 40)], usage=Usage(total=100)
        ),
        UserMessage("n" * 16),
    ]
    assert estimate_context_tokens(messages, usage_valid=True) == 104
    assert estimate_context_tokens(messages, usage_valid=False) == 34


@pytest.mark.asyncio
async def test_split_turn_summary_preserves_history_and_current_turn_separately():
    adapter = ScriptedAdapter([["Past facts"], ["Current question"]])
    models, model = make_models(adapter)
    try:
        result, _ = await summarize(
            models,
            model,
            [UserMessage("Past")],
            [UserMessage("Question")],
            None,
            SimpleOptions(),
        )
        assert result == "Past facts\n\n---\n\n**Turn Context (split turn):**\n\nCurrent question"
        assert len(adapter.inputs) == 2
    finally:
        await models.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_or_cancelled_compaction_keeps_original_path(
    session_service,
    database,
    tmp_path,
    cancelled,
):
    from ai import AbortController
    from sqlalchemy import select

    from dialogue_lab.sessions.types import SessionError
    from dialogue_lab.storage.tables import compactions

    (tmp_path / "default.md").write_text("Brief", encoding="utf-8")
    controller = AbortController()

    class FailingAdapter(ScriptedAdapter):
        async def stream_simple(self, model, context, auth, options):
            if cancelled:
                controller.abort()
            else:
                raise RuntimeError("provider failed")
            async for event in super().stream_simple(model, context, auth, options):
                yield event

    models, model = make_models(FailingAdapter([["unused"]]))
    session_id = int((await session_service.create("Practice"))["session_id"])
    for text in ("a" * 80, "b" * 40):
        await session_service.submit(session_id, uuid4(), text)
    manager = ContextManager(
        session_service,
        models,
        model,
        SystemPrompts(tmp_path),
        CompactionStore(database),
        CompactionSettings(keep_recent_tokens=10),
    )
    before = await session_service.path(session_id)
    try:
        prepared = await manager.build(session_id, "default")
        with pytest.raises(SessionError):
            await manager.compact(session_id, prepared, SimpleOptions(signal=controller.signal))
        assert await session_service.path(session_id) == before
        async with database.engine.connect() as connection:
            status = (await connection.execute(select(compactions.c.status))).scalar_one()
        assert status == ("cancelled" if cancelled else "failed")
    finally:
        await models.aclose()


@pytest.mark.parametrize(
    "name, content, code",
    [
        ("missing", None, "PRESET_NOT_FOUND"),
        ("empty", "  ", "PRESET_EMPTY"),
    ],
)
def test_unavailable_prompt_does_not_become_empty_instructions(tmp_path, name, content, code):
    from dialogue_lab.sessions.types import SessionError

    if content is not None:
        (tmp_path / f"{name}.md").write_text(content, encoding="utf-8")
    with pytest.raises(SessionError) as caught:
        SystemPrompts(tmp_path).load(name)
    assert caught.value.code == code


@pytest.mark.asyncio
async def test_context_uses_parent_path_and_excludes_inactive_branch(
    session_service, database, tmp_path
):
    from sqlalchemy import update

    from dialogue_lab.storage.tables import sessions

    (tmp_path / "default.md").write_text("Brief", encoding="utf-8")
    models, model = make_models(ScriptedAdapter([]))
    session_id = int((await session_service.create("Branch"))["session_id"])
    await session_service.submit(session_id, uuid4(), "Root")
    root = (await session_service.path(session_id))[-1]["entry_id"]
    await session_service.submit(session_id, uuid4(), "Inactive branch")
    # 本步骤没有分支编辑界面；测试用真实存储建立另一条父节点路径。
    async with database.engine.begin() as connection:
        await connection.execute(
            update(sessions).where(sessions.c.session_id == session_id).values(active_entry_id=root)
        )
    await session_service.submit(session_id, uuid4(), "Current branch")
    manager = ContextManager(session_service, models, model, SystemPrompts(tmp_path))
    try:
        prepared = await manager.build(session_id, "default")
        assert [m.content[0].text for m in prepared.messages[1:]] == ["Root", "Current branch"]
    finally:
        await models.aclose()
