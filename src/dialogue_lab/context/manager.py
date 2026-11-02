"""上下文公开入口：加载、路径投影、预算与压缩；不调度用户输入。"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import asdict

from ai import AbortSignal, AssistantMessage, Context, UserMessage

from dialogue_lab.context.compaction import (
    CompactionSettings,
    estimate_context_tokens,
    find_cut_point,
    summarize,
)
from dialogue_lab.context.messages import (
    ApplicationMessage,
    CompactionSummary,
    application_snapshot,
    convert_to_llm,
)
from dialogue_lab.context.session_projection import project_path
from dialogue_lab.context.types import PreparedContext
from dialogue_lab.memory.service import MemoryService
from dialogue_lab.sessions.types import SessionError
from dialogue_lab.storage.memory_store import MemoryStore

type TransformContext = Callable[
    [list[ApplicationMessage], AbortSignal | None], Awaitable[list[ApplicationMessage]]
]


class ContextManager:
    """准备会话材料、独立压缩，并为每次回复组装完整 Context。"""

    def __init__(
        self,
        sessions,
        models,
        model,
        prompts,
        compactions=None,
        settings=None,
        *,
        transform_context: TransformContext | None = None,
        character_store=None,
        memory=None,
    ):
        self.sessions, self.models, self.model = sessions, models, model
        self.prompts, self.compactions, self.settings = prompts, compactions, settings
        self.settings = settings or CompactionSettings()
        self.transform_context = transform_context
        self.character_store = character_store
        self.memory = memory or MemoryService(MemoryStore(sessions.store.database))
        # 只复用与材料键匹配的用量，不缓存模型输出。
        self._usage_system = {}

    def select_model(self, model):
        """运行时仅在操作开始时切换模型；旧模型的用量不能用于新模型预算。"""
        if model != self.model:
            self._usage_system.clear()
            self.model = model

    async def build(self, session_id: int, preset: str, tools=None) -> PreparedContext:
        """读取当前文档和有效路径；此时不执行请求级消息调整。"""
        system = await asyncio.to_thread(self.prompts.load, preset)
        if self.character_store is not None:
            character = await self.character_store.find_for_session(session_id)
            if character is not None:
                # 文档保存模板；当次使用当前名字，预算和材料键均按替换后的正文计算。
                system = system.replace("{{character_name}}", character["character_name"])
        path = await self.sessions.path(session_id)
        revision, withdrawn = await self.memory.projection_state(session_id)
        projected = project_path(path, self.models, revision, withdrawn)
        messages = [message for _, message in projected]
        state = await self.sessions.state(session_id)
        memories = await self.memory.core(session_id)
        retained_ids = {entry_id for entry_id, _ in projected}
        retained_memories = {
            memory_id
            for row in path
            if row["entry_id"] in retained_ids
            and row["entry_type"] == "message"
            and row["message_kind"] == "tool_result"
            and row["request_id"] not in withdrawn
            for memory_id in row["message_json"].get("memory_refs", {})
        }
        selected, omitted = [], []
        memory_tokens = 0
        for item in memories:
            if str(item.id) in retained_memories:
                continue
            cost = (len(json.dumps(asdict(item), ensure_ascii=False)) + 3) // 4
            if memory_tokens + cost > self.settings.memory_tokens:
                omitted.append(item.id)
            else:
                selected.append(item)
                memory_tokens += cost
        snapshot = application_snapshot(state, selected)
        if tools:
            system += (
                "\n建立、修改或结束持续交流约定时调用 update_session_state；"
                "一次性问题不改状态。工具成功后才能声称保存。"
            )
        cache_key = system + (snapshot.content if snapshot else "") + repr(tools) + str(revision)
        projected_messages = ([snapshot] if snapshot else []) + messages
        memory_refs = {str(item.id): item.revision for item in selected}
        for row in path:
            if row["entry_type"] == "message" and row["request_id"] not in withdrawn:
                memory_refs.update(row["message_json"].get("memory_refs", {}))
        return PreparedContext(
            system_prompt=system,
            messages=messages,
            entry_ids=[entry_id for entry_id, _ in projected],
            anchor_entry_id=path[-1]["entry_id"] if path else None,
            cache_key=cache_key,
            tokens=estimate_context_tokens(
                projected_messages,
                usage_valid=(
                    self.transform_context is None
                    and self._usage_system.get(session_id) == cache_key
                ),
                system_prompt=system,
                tools=tools,
            ),
            tools=tools or [],
            session_state=state,
            memories=selected,
            memory_revision=revision,
            memory_refs=memory_refs,
            report={
                "entry_ids": [entry_id for entry_id, _ in projected],
                "summary_entry_ids": [
                    entry_id
                    for entry_id, message in projected
                    if isinstance(message, CompactionSummary)
                ],
                "memory_ids": [m.id for m in selected],
                "memory_tokens": memory_tokens,
                "omitted_memory_ids": omitted,
                "history_memory_ids": sorted(int(value) for value in retained_memories),
            },
        )

    async def to_context(
        self,
        prepared: PreparedContext,
        signal: AbortSignal | None = None,
        *,
        max_output_tokens: int | None = None,
    ) -> Context:
        """组装 AI 层公开输入；规范化和供应商协议转换由 AI 层执行。"""
        if signal and signal.aborted:
            raise asyncio.CancelledError
        # 回调可就地编辑消息；副本隔离本次请求与准备结果、后续压缩。
        messages = deepcopy(prepared.messages)
        if self.transform_context is not None:
            messages = await self.transform_context(messages, signal)
        if signal and signal.aborted:
            raise asyncio.CancelledError
        context = Context(
            system_prompt=prepared.system_prompt,
            messages=(
                [snapshot]
                if (snapshot := application_snapshot(prepared.session_state, prepared.memories))
                else []
            )
            + convert_to_llm(messages),
            tools=deepcopy(prepared.tools),
        )
        tokens = estimate_context_tokens(
            context.messages,
            usage_valid=False,
            system_prompt=context.system_prompt,
            tools=context.tools,
        )
        if self.transform_context is None:
            tokens = max(prepared.tokens, tokens)
        prepared.report.update(
            {
                "estimated_tokens": tokens,
                "system_tokens": (len(context.system_prompt) + 3) // 4,
                "snapshot_tokens": (len(snapshot.content) + 3) // 4 if snapshot else 0,
                "history_tokens": estimate_context_tokens(
                    context.messages[1:] if snapshot else context.messages,
                    usage_valid=False,
                ),
                "tool_tokens": estimate_context_tokens([], usage_valid=False, tools=context.tools),
                "memory_revision": prepared.memory_revision,
            }
        )
        reserve = max_output_tokens or self.settings.reserve_tokens
        if self.model.context_window is not None and tokens > self.model.context_window - reserve:
            raise SessionError("CONTEXT_TOO_LARGE", "当前输入超过模型窗口，压缩后仍无法发送。")
        return context

    def remember_usage(self, session_id: int, prepared: PreparedContext):
        # 调整后的请求不代表完整会话，不能用其用量判断原始上下文的压缩时机。
        if self.transform_context is None:
            self._usage_system[session_id] = prepared.cache_key
        else:
            self._usage_system.pop(session_id, None)

    async def compact(self, session_id, prepared, options, trigger="manual"):
        dialogue = prepared.messages
        entry_ids = prepared.entry_ids
        previous = None
        if dialogue and isinstance(dialogue[0], CompactionSummary):
            previous = dialogue[0].summary
            dialogue, entry_ids = dialogue[1:], entry_ids[1:]
        cut = find_cut_point(dialogue, self.settings.keep_recent_tokens)
        if cut == 0:
            return False
        history_end = cut
        turn_prefix = []
        if isinstance(dialogue[cut], AssistantMessage):
            start = next(
                (
                    index
                    for index in range(cut - 1, -1, -1)
                    if isinstance(dialogue[index], UserMessage)
                ),
                None,
            )
            if start is not None:
                history_end = start
                turn_prefix = dialogue[start:cut]
        compaction_id = await self.compactions.begin(
            session_id,
            prepared.anchor_entry_id,
            trigger,
            prepared.memory_revision,
        )
        try:
            summary, usage = await summarize(
                self.models, self.model, dialogue[:history_end], turn_prefix, previous, options
            )
            if options.signal and options.signal.aborted:
                raise SessionError("COMPACTION_CANCELLED", "上下文压缩已取消。")
            await self.compactions.apply(
                session_id,
                compaction_id,
                entry_ids[cut - 1],
                entry_ids[cut],
                summary,
                asdict(usage),
            )
            self._usage_system.pop(session_id, None)
            return True
        except BaseException as error:
            cancelled = isinstance(error, asyncio.CancelledError) or (
                isinstance(error, SessionError) and error.code == "COMPACTION_CANCELLED"
            )
            await self.compactions.fail(
                compaction_id,
                "cancelled" if cancelled else "failed",
                "COMPACTION_CANCELLED" if cancelled else "COMPACTION_FAILED",
                "压缩未完成，原始路径保持不变。",
            )
            raise

    def needs_compaction(self, prepared):
        window = self.model.context_window
        return (
            self.settings.enabled
            and window is not None
            and prepared.tokens > window - self.settings.reserve_tokens
        )
