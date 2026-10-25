"""上下文公开入口：加载、路径投影、预算与压缩；不调度用户输入。"""

import asyncio
from dataclasses import asdict, dataclass
from hashlib import sha256

from ai import AssistantMessage, UserMessage

from dialogue_lab.context.compaction import (
    CompactionSettings,
    estimate_context_tokens,
    find_cut_point,
    summarize,
)
from dialogue_lab.context.messages import ApplicationMessage, CompactionSummary
from dialogue_lab.context.session_projection import project_path
from dialogue_lab.sessions.types import SessionError


@dataclass
class PreparedContext:
    messages: list[ApplicationMessage]
    entry_ids: list[int]
    anchor_entry_id: int | None
    system_hash: str
    tokens: int


class ContextManager:
    def __init__(self, sessions, models, model, prompts, compactions=None, settings=None):
        self.sessions, self.models, self.model = sessions, models, model
        self.prompts, self.compactions, self.settings = prompts, compactions, settings
        self.settings = settings or CompactionSettings()
        # 只保存用于判断用量是否仍有效的摘要；不缓存或持久化指令正文。
        self._usage_system = {}

    async def build(self, session_id: int, preset: str):
        system = await asyncio.to_thread(self.prompts.load, preset)
        path = await self.sessions.path(session_id)
        projected = project_path(path, self.models)
        messages = [system, *(message for _, message in projected)]
        fingerprint = sha256(system.content.encode()).hexdigest()
        return PreparedContext(
            messages,
            [entry_id for entry_id, _ in projected],
            path[-1]["entry_id"] if path else None,
            fingerprint,
            estimate_context_tokens(
                messages, usage_valid=(self._usage_system.get(session_id) == fingerprint)
            ),
        )

    def remember_usage(self, session_id: int, prepared: PreparedContext):
        self._usage_system[session_id] = prepared.system_hash

    async def compact(self, session_id, prepared, options, trigger="manual"):
        dialogue = prepared.messages[1:]
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
