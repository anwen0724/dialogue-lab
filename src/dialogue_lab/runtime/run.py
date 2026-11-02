"""一次输入的模型、工具和输出循环；会话准入由 Scheduler 决定。"""

import asyncio
import logging
from dataclasses import replace

from ai import AbortController, ToolCall

from dialogue_lab.runtime.model_call import call_model
from dialogue_lab.sessions.types import SessionError, visible_message
from dialogue_lab.voice.output import stream_speech

logger = logging.getLogger(__name__)


class Run:
    def __init__(
        self,
        session_id,
        request,
        sessions,
        context,
        tools,
        emit,
        output,
        compact,
        max_tool_rounds=8,
    ):
        self.session_id, self.request = session_id, request
        self.sessions, self.context, self.tools = sessions, context, tools
        self.emit, self.output, self.compact = emit, output, compact
        self.max_tool_rounds = max_tool_rounds
        self.id = str(request.request_id)
        self.controller = AbortController()
        self.output_enabled = True
        self.playback_done = False

    def stop(self):
        self.output_enabled = False
        self.controller.abort()

    async def execute(self, models, model, options, synthesis_factory):
        signal = self.controller.signal
        texts = asyncio.Queue()
        speech = None
        started = False
        step = 0

        async def output(event):
            await self.output(self.id, event)

        async def forward(event):
            await output(event)
            if not signal.aborted:
                texts.put_nowait(event["text"])

        try:
            definitions = await self.tools.definitions(self.session_id)
            for round_index in range(self.max_tool_rounds + 1):
                prepared = await self.context.build(
                    self.session_id,
                    self.request.preset,
                    definitions,
                )
                prepared = await self.compact(self.request, prepared, self.controller)
                if signal.aborted:
                    return
                context = await self.context.to_context(
                    prepared,
                    signal,
                    max_output_tokens=options.max_output_tokens,
                )
                logger.debug(
                    "Context run=%s round=%s report=%s", self.id, round_index, prepared.report
                )
                if not started:
                    await output({"type": "reply_started"})
                    started = True
                    if synthesis_factory is not None:
                        speech = asyncio.create_task(
                            stream_speech(synthesis_factory, texts, signal, output)
                        )
                result = await call_model(
                    models,
                    model,
                    context,
                    replace(options, signal=signal),
                    forward,
                )
                saved = await self.sessions.save_assistant(
                    self.session_id,
                    self.request.request_id,
                    result,
                    step,
                    prepared.memory_refs,
                )
                step += 1
                if visible_message(saved):
                    await self.emit({"type": "message_saved", "message": saved})
                calls = [b for b in result.content if isinstance(b, ToolCall)]
                if signal.aborted or result.stop_reason in ("error", "aborted"):
                    break
                self.context.remember_usage(self.session_id, prepared)
                if not calls:
                    break
                if round_index == self.max_tool_rounds:
                    raise SessionError("TOOL_LIMIT", "本轮工具调用达到上限，请重新说明需求。")
                for call in calls:
                    if signal.aborted:
                        return
                    await self.tools.execute(
                        self.session_id,
                        self.request.request_id,
                        step,
                        call,
                        signal,
                    )
                    step += 1
            # 最后一轮正文结束即可排空 TTS，不等待后置摘要。
            texts.put_nowait(None)
            await output({"type": "generation_finished", "status": saved["message_json"]["status"]})
            if not signal.aborted and result.stop_reason not in ("error", "aborted"):
                prepared = await self.context.build(
                    self.session_id,
                    self.request.preset,
                    definitions,
                )
                await self.compact(self.request, prepared, self.controller)
        except asyncio.CancelledError:
            if not signal.aborted:
                raise
        except Exception as error:
            if not started:
                self.playback_done = True
            await output(
                {
                    "type": "error",
                    "code": error.code if isinstance(error, SessionError) else "REPLY_FAILED",
                    "message": str(error)
                    if isinstance(error, SessionError)
                    else "未能完成回复，请检查配置后重试。",
                }
            )
            if started:
                await output({"type": "generation_finished", "status": "failed"})
        finally:
            texts.put_nowait(None)
            try:
                await self.sessions.close_pending_tools(self.session_id)
            finally:
                if speech is not None:
                    await speech
                else:
                    await output({"type": "audio_finished"})
