"""将 speechio 的流式合成接口接入异步应用。"""

import anyio
import speechio


class Synthesis:
    def __init__(self, *, api_key: str, model: str, voice: str, provider: str = "bailian"):
        self._config = speechio.RemoteModelConfig(provider=provider, model=model, api_key=api_key)
        self._voice = voice
        self._synthesizer = None
        self._stream = None

    async def __aenter__(self):
        try:
            await anyio.to_thread.run_sync(self._open)
        except BaseException:
            await self.aclose()
            raise
        return self

    def _open(self):
        self._synthesizer = speechio.Synthesizer(self._config)
        self._stream = self._synthesizer.open_stream(
            options=speechio.SynthesisOptions(voice=self._voice, text_timestamps="word")
        )

    async def send_text(self, text: str):
        await anyio.to_thread.run_sync(self._stream.send_text, text)

    async def finish_input(self):
        await anyio.to_thread.run_sync(self._stream.finish_input)

    async def events(self):
        """并发读取音频和文字时间；同一句的后续时间事件更新已有信息。"""
        iterator = self._stream.events()
        sentinel = object()
        while True:
            chunk = await anyio.to_thread.run_sync(next, iterator, sentinel)
            if chunk is sentinel:
                return
            yield chunk

    async def cancel(self):
        if self._stream is not None:
            await anyio.to_thread.run_sync(self._stream.cancel)

    async def aclose(self):
        """先解除音频读取等待，再释放任务与合成器。"""
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(self._close)

    def _close(self):
        results = []
        try:
            if self._stream is not None:
                results.append(self._stream.close())
        finally:
            if self._synthesizer is not None:
                results.append(self._synthesizer.close())
        if any(result.status != "ok" for result in results):
            raise RuntimeError("合成资源尚未正常释放。")

    async def __aexit__(self, *_):
        await self.aclose()
