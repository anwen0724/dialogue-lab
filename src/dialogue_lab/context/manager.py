"""上下文公开入口：加载、路径投影、预算与压缩；不调度用户输入。"""

import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from hashlib import sha256

from ai import AbortSignal, AssistantMessage, Context, Tool, UserMessage

from dialogue_lab.context.compaction import (
    CompactionSettings,
    estimate_context_tokens,
    find_cut_point,
    summarize,
)
from dialogue_lab.context.messages import ApplicationMessage, CompactionSummary, convert_to_llm
from dialogue_lab.context.session_projection import project_path
from dialogue_lab.sessions.types import SessionError

type TransformContext = Callable[
    [list[ApplicationMessage], AbortSignal | None], Awaitable[list[ApplicationMessage]]
]


@dataclass
class PreparedContext:
    """内部准备结果，分别保存指令正文、应用消息和压缩定位信息。"""

    system_prompt: str
    messages: list[ApplicationMessage]
    entry_ids: list[int]
    anchor_entry_id: int | None
    system_hash: str
    tokens: int
    tools: list[Tool] = field(default_factory=list)


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
        scene_store=None,
    ):
        self.sessions, self.models, self.model = sessions, models, model
        self.prompts, self.compactions, self.settings = prompts, compactions, settings
        self.settings = settings or CompactionSettings()
        self.transform_context = transform_context
        self.scene_store = scene_store
        # 只保存用于判断用量是否仍有效的摘要；不缓存或持久化指令正文。
        self._usage_system = {}

    async def build(self, session_id: int, preset: str) -> PreparedContext:
        """读取当前文档和有效路径；此时不执行请求级消息调整。"""
        system = await asyncio.to_thread(self.prompts.load, preset)
        if self.scene_store is not None:
            scene = await self.scene_store.find_for_session(session_id)
            if scene is not None:
                # 文档保存模板；当次使用当前名字，预算和指纹均按替换后的正文计算。
                system = system.replace("{{character_name}}", scene["character_name"])
        path = await self.sessions.path(session_id)
        projected = project_path(path, self.models)
        messages = [message for _, message in projected]
        fingerprint = sha256(system.encode()).hexdigest()
        return PreparedContext(
            system_prompt=system,
            messages=messages,
            entry_ids=[entry_id for entry_id, _ in projected],
            anchor_entry_id=path[-1]["entry_id"] if path else None,
            system_hash=fingerprint,
            tokens=estimate_context_tokens(
                messages,
                usage_valid=(
                    self.transform_context is None
                    and self._usage_system.get(session_id) == fingerprint
                ),
                system_prompt=system,
            ),
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
            messages=convert_to_llm(messages),
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
        reserve = max_output_tokens or self.settings.reserve_tokens
        if self.model.context_window is not None and tokens > self.model.context_window - reserve:
            raise SessionError("CONTEXT_TOO_LARGE", "当前输入超过模型窗口，压缩后仍无法发送。")
        return context

    def remember_usage(self, session_id: int, prepared: PreparedContext):
        # 调整后的请求不代表完整会话，不能用其用量判断原始上下文的压缩时机。
        if self.transform_context is None:
            self._usage_system[session_id] = prepared.system_hash
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
        compaction_id = await self.compactions.begin(session_id, prepared.anchor_entry_id, trigger)
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
