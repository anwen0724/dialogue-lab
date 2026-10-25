"""每个 Session 的调度器，负责输入准入、保存时点和活动输出归属。"""

import asyncio
from dataclasses import replace

from ai import AbortController, SimpleOptions

from dialogue_lab.context.messages import convert_to_llm
from dialogue_lab.runtime.model_call import call_model, stream_speech
from dialogue_lab.sessions.types import SessionError


class Scheduler:
    def __init__(
        self,
        session_id,
        sessions,
        context,
        models,
        model,
        emit,
        options=None,
        synthesis_factory=None,
    ):
        self.session_id, self.sessions, self.context = session_id, sessions, context
        self.models, self.model, self.emit = models, model, emit
        self.options, self.synthesis_factory = options, synthesis_factory
        self.options = options or SimpleOptions()
        self._commands = asyncio.Queue()
        self._worker = None
        self._controller = None
        self._active = None
        self._closed = False
        self._compacting = False
        self._manual = False
        self._playback_done = False
        self._waiting = []
        self._idle = asyncio.Event()
        self._idle.set()
        self._actor = asyncio.create_task(self._serve())

    async def submit(self, request):
        return await self._command("submit", request)

    async def wait_idle(self):
        await self._idle.wait()

    async def close(self):
        if self._closed:
            return
        await self._command("close")
        await self._actor

    async def stop(self):
        await self._command("stop")

    async def compact(self, preset):
        return await self._command("compact", preset)

    async def playback_finished(self, request_id):
        await self._command("played", request_id)

    async def _command(self, kind, value=None):
        if self._closed:
            raise SessionError("CONNECTION_CLOSED", "会话连接已关闭。")
        future = asyncio.get_running_loop().create_future()
        self._commands.put_nowait((kind, value, future))
        return await future

    async def _serve(self):
        """命令读取不等待整个生成周期；生成和取消收尾各自有明确归属。"""
        while True:
            kind, value, future = await self._commands.get()
            try:
                result = None
                if kind == "submit":
                    if self._compacting:
                        if self._manual:
                            raise SessionError("COMPACTION_BUSY", "手动压缩中，请等待完成后提交。")
                        self._waiting.append((kind, value, future))
                        await self.emit(
                            {"type": "input_queued", "request_id": str(value.request_id)}
                        )
                        continue
                    result = await self._accept(value)
                elif kind == "compact":
                    if self._compacting:
                        raise SessionError("COMPACTION_BUSY", "正在压缩，请等待完成。")
                    await self._stop()
                    self._compacting = self._manual = True
                    self._idle.clear()
                    self._controller = AbortController()
                    self._worker = asyncio.create_task(self._manual_compact(value, future))
                    continue
                elif kind in ("stop", "close"):
                    if kind == "stop" and self._active is None:
                        await self.emit({"type": "reply_stopped", "request_id": None})
                    await self._stop()
                    if kind == "close":
                        self._closed = True
                        for _, _, pending in self._waiting:
                            if not pending.done():
                                pending.set_exception(
                                    SessionError("CONNECTION_CLOSED", "连接已关闭。")
                                )
                        self._waiting.clear()
                elif kind == "compacted":
                    self._compacting = False
                    self._manual = False
                    for command in self._waiting:
                        self._commands.put_nowait(command)
                    self._waiting.clear()
                elif kind == "finished" and value == self._active:
                    self._worker = None
                    self._idle.set()
                    if self._playback_done:
                        self._active = None
                elif kind == "played" and value == self._active:
                    self._playback_done = True
                    if self._worker is None:
                        self._active = None
                if future is not None and not future.done():
                    future.set_result(result)
                if self._closed:
                    while not self._commands.empty():
                        _, _, pending = self._commands.get_nowait()
                        if pending is not None and not pending.done():
                            pending.set_exception(SessionError("CONNECTION_CLOSED", "连接已关闭。"))
                    return
            except Exception as error:
                if future is not None and not future.done():
                    future.set_exception(error)
                else:
                    await self.emit(
                        {
                            "type": "error",
                            "code": "RUNTIME_FAILED",
                            "message": "会话处理失败，请重试。",
                        }
                    )

    async def _accept(self, request):
        existing = await self.sessions.find_request(
            self.session_id, request.request_id, request.text, request.source
        )
        if existing is not None:
            await self.emit({"type": "message_saved", "message": existing})
            return existing
        # 校验预设后才取消旧回复；上下文构建仍会按 D1 读取当次文档。
        await asyncio.to_thread(self.context.prompts.load, request.preset)
        await self._stop()
        message, _ = await self.sessions.submit(
            self.session_id, request.request_id, request.text, request.source
        )
        await self.emit({"type": "message_saved", "message": message})
        self._active = str(request.request_id)
        self._playback_done = False
        self._controller = AbortController()
        self._idle.clear()
        self._worker = asyncio.create_task(self._reply(request, self._controller))
        return message

    async def _reply(self, request, controller):
        request_id = str(request.request_id)
        speech = None
        texts = asyncio.Queue()
        try:
            prepared = await self.context.build(self.session_id, request.preset)
            prepared = await self._maybe_compact(request, prepared, controller)
            if controller.signal.aborted:
                return
            reserve = self.options.max_output_tokens or self.context.settings.reserve_tokens
            if self.model.context_window is not None and (
                prepared.tokens > self.model.context_window - reserve
            ):
                raise SessionError("CONTEXT_TOO_LARGE", "当前输入超过模型窗口，压缩后仍无法发送。")
            await self._output(request_id, {"type": "reply_started"})

            async def audio_output(event):
                await self._output(request_id, event)

            if self.synthesis_factory is not None:
                speech = asyncio.create_task(
                    stream_speech(self.synthesis_factory, texts, controller.signal, audio_output)
                )

            async def forward(event):
                await self._output(request_id, event)
                if not controller.signal.aborted:
                    texts.put_nowait(event["text"])

            result = await call_model(
                self.models,
                self.model,
                convert_to_llm(prepared.messages),
                replace(self.options, signal=controller.signal),
                forward,
            )
            texts.put_nowait(None)
            message = await self.sessions.save_assistant(
                self.session_id, request.request_id, result
            )
            await self.emit({"type": "message_saved", "message": message})
            if result.stop_reason not in ("error", "aborted"):
                self.context.remember_usage(self.session_id, prepared)
            await self._output(
                request_id,
                {"type": "generation_finished", "status": message["message_json"]["status"]},
            )
            if not controller.signal.aborted and result.stop_reason not in ("error", "aborted"):
                updated = await self.context.build(self.session_id, request.preset)
                await self._maybe_compact(request, updated, controller)
        except Exception as error:
            await self._output(
                request_id,
                {
                    "type": "error",
                    "code": error.code if isinstance(error, SessionError) else "REPLY_FAILED",
                    "message": str(error)
                    if isinstance(error, SessionError)
                    else "未能完成回复，请检查配置后重试。",
                },
            )
        finally:
            texts.put_nowait(None)
            if speech is not None:
                await speech
            else:
                await self._output(request_id, {"type": "audio_finished"})
            self._commands.put_nowait(("finished", request_id, None))

    async def _maybe_compact(self, request, prepared, controller):
        if not self.context.needs_compaction(prepared) or controller.signal.aborted:
            return prepared
        self._compacting = True
        await self.emit({"type": "compaction_started"})
        try:
            changed = await self.context.compact(
                self.session_id, prepared, replace(self.options, signal=controller.signal), "auto"
            )
            await self.emit(
                {"type": "compaction_finished", "status": "completed" if changed else "unchanged"}
            )
            return (
                await self.context.build(self.session_id, request.preset) if changed else prepared
            )
        except SessionError as error:
            await self.emit({"type": "compaction_finished", "status": "failed", "code": error.code})
            return prepared
        finally:
            self._commands.put_nowait(("compacted", None, None))

    async def _manual_compact(self, preset, future):
        await self.emit({"type": "compaction_started"})
        try:
            prepared = await self.context.build(self.session_id, preset)
            changed = await self.context.compact(
                self.session_id, prepared, replace(self.options, signal=self._controller.signal)
            )
            await self.emit(
                {"type": "compaction_finished", "status": "completed" if changed else "unchanged"}
            )
            if not future.done():
                future.set_result(changed)
        except Exception as error:
            await self.emit({"type": "compaction_finished", "status": "failed"})
            if not future.done():
                future.set_exception(error)
        finally:
            self._commands.put_nowait(("compacted", None, None))
            self._commands.put_nowait(("finished", None, None))

    async def _output(self, request_id, event):
        if self._active == request_id:
            await self.emit({**event, "request_id": request_id})

    async def _stop(self):
        """先撤销输出资格，再传播取消并等待旧消息保存完成。"""
        previous = self._active
        self._active = None
        if previous is not None:
            await self.emit({"type": "reply_stopped", "request_id": previous})
        if self._controller is not None:
            self._controller.abort()
        if self._worker is not None:
            await self._worker
            self._worker = None
        self._idle.set()
