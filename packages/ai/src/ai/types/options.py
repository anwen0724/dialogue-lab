"""通用请求选项不依赖供应商 SDK。"""

import asyncio
from dataclasses import dataclass, field

from ai.auth.contracts import ModelAuth
from ai.hooks import Hook
from ai.types.model import ReasoningLevel


class AbortSignal:
    """调用者可观察的取消信号。"""

    def __init__(self):
        self._event = asyncio.Event()

    @property
    def aborted(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


class AbortController:
    """宿主持有控制器，模型调用只接收 signal。"""

    def __init__(self):
        self.signal = AbortSignal()

    def abort(self) -> None:
        self.signal._event.set()


@dataclass(kw_only=True)
class RequestOptions:
    auth: ModelAuth | None = None
    headers: dict[str, str] = field(default_factory=dict)
    signal: AbortSignal | None = None
    timeout: float | None = None
    max_retries: int = 0
    observer: Hook | None = None
    transform_headers: Hook | None = None
    on_payload: Hook | None = None
    on_response: Hook | None = None
    on_provider_stream_event: Hook | None = None


@dataclass(kw_only=True)
class SimpleOptions(RequestOptions):
    temperature: float | None = None
    max_output_tokens: int | None = None
    reasoning: ReasoningLevel | None = None
