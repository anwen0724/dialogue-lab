"""流式正文到语音输出；负责合成任务和取消收尾。"""

import asyncio
from dataclasses import asdict

import speechio


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
                async for chunk in synthesis.events():
                    if signal.aborted:
                        break
                    if isinstance(chunk, speechio.TextTiming):
                        await emit({"type": "text_timing", **asdict(chunk)})
                        continue
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
