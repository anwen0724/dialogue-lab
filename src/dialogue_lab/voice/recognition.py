"""把 speechio 的同步自动识别会话转换为应用可消费的异步事件。"""

from collections.abc import AsyncIterator
from functools import partial
from time import monotonic

import anyio
import speechio


class VoiceInputError(Exception):
    """可交付给页面的错误，不包含供应商原始响应或凭据。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Recognition:
    """每个输入连接独占识别资源；正常结束排空，退出时取消剩余任务。"""

    def __init__(self, *, api_key: str, model: str):
        self._config = speechio.RemoteModelConfig(provider="bailian", model=model, api_key=api_key)
        self._runtime = None
        self._session = None
        self._finish_deadline: float | None = None

    async def __aenter__(self):
        # 不放弃加载线程；否则取消连接后，迟到创建的模型无人关闭。
        try:
            await anyio.to_thread.run_sync(self._open)
        except BaseException:
            await self.aclose()
            raise
        return self

    def _open(self) -> None:
        self._runtime = speechio.STTRuntime(
            self._config, realtime=speechio.RealtimeConfig(mode="streaming")
        )
        self._runtime.prepare()
        self._session = self._runtime.create_auto_session(
            config=speechio.SessionConfig(
                format=speechio.AudioFormat(sample_rate=16000, channels=1, sample_type="int16"),
                realtime=True,
            )
        )

    async def feed_audio(self, audio: bytes) -> None:
        """按到达顺序送入 PCM；由调用方串行调用。"""
        await anyio.to_thread.run_sync(self._session.feed_audio, audio)

    async def finish_input(self) -> None:
        """封口但不取消识别；读取事件的一方继续交付尾部结果。"""
        await anyio.to_thread.run_sync(self._session.end_input)
        self._finish_deadline = monotonic() + 30

    async def events(self) -> AsyncIterator[dict]:
        """只转发临时文字与最终文字，完成事件由包内部用于排空分段。"""
        while True:
            if self._finish_deadline is not None:
                if not self._session.pending_segments:
                    return
                if monotonic() >= self._finish_deadline:
                    raise VoiceInputError(
                        "STT_FINISH_TIMEOUT", "结束识别超时，最后一段可能未完成。"
                    )
            event = await anyio.to_thread.run_sync(partial(self._session.next_event, timeout=0.1))
            if event is None:
                continue
            if event.error is not None:
                raise VoiceInputError("STT_FAILED", "语音识别失败，请检查语音配置和网络后重试。")
            if event.kind in ("realtime", "final") and event.result is not None:
                yield {
                    "type": "final" if event.kind == "final" else "partial",
                    "segment_id": event.turn.turn_id,
                    "text": event.result.text,
                }

    async def aclose(self) -> None:
        """即使连接已取消也完成关闭；pending 不伪装成关闭成功。"""
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(self._close)

    def _close(self) -> None:
        try:
            if self._session is not None:
                self._session.close()
        finally:
            if self._runtime is not None:
                result = self._runtime.close(timeout=5.0)
                if result.status != "ok":
                    raise VoiceInputError("STT_CLOSE_FAILED", "识别资源尚未正常释放，请稍后重试。")

    async def __aexit__(self, *_):
        await self.aclose()
