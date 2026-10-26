"""执行一次模型调用并交付正文增量及结束结果，不访问数据库。"""

import asyncio
from copy import deepcopy
from dataclasses import replace

from ai import Context


async def call_model(models, model, context: Context, options, emit):
    """仅交付正文；思考和工具参数留在最终消息，不送到语音通道。"""
    stream = models.stream_simple(model, context, options)
    draft = None
    async for event in stream:
        if event.type not in ("done", "error"):
            draft = event.partial
        if event.type == "text_delta":
            await emit({"type": "text_delta", "text": event.delta})
    result = await stream.result()
    # AI 调用层在外层取消时可能返回空终态；宿主保留已经收到的草稿。
    if result.stop_reason in ("aborted", "error") and not result.content and draft is not None:
        result = replace(result, content=deepcopy(draft.content), usage=deepcopy(draft.usage))
    return result


async def stream_speech(factory, texts, signal, emit):
    """文本与音频并行推进；合成失败只关闭语音输出，不取消文字生成。"""
    try:
        first = await texts.get()
        if first is None or signal.aborted:
            return
        async with factory() as synthesis:

            async def send():
                await synthesis.send_text(first)
                while (text := await texts.get()) is not None:
                    await synthesis.send_text(text)
                await synthesis.finish_input()

            async def receive():
                announced = False
                async for chunk in synthesis.audio():
                    if signal.aborted:
                        break
                    if not announced:
                        await emit(
                            {
                                "type": "audio_format",
                                "sample_rate": chunk.format.sample_rate,
                                "channels": chunk.format.channels,
                                "encoding": "pcm_s16le",
                            }
                        )
                        announced = True
                    await emit({"type": "audio", "data": chunk.data})

            sender = asyncio.create_task(send())
            receiver = asyncio.create_task(receive())

            async def cancel_on_signal():
                await signal.wait()
                await synthesis.cancel()
                sender.cancel()

            watcher = asyncio.create_task(cancel_on_signal())
            try:
                await asyncio.gather(sender, receiver)
            except BaseException:
                await synthesis.cancel()
                sender.cancel()
                receiver.cancel()
                await asyncio.gather(sender, receiver, return_exceptions=True)
                if not signal.aborted:
                    raise
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
    except Exception:
        if not signal.aborted:
            await emit(
                {
                    "type": "error",
                    "code": "TTS_FAILED",
                    "message": "语音合成失败，文字回复仍会保存。",
                }
            )
    finally:
        if not signal.aborted:
            await emit({"type": "audio_finished"})
