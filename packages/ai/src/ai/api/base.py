"""协议扩展契约。"""

from collections.abc import AsyncIterator
from typing import Protocol

from ai.auth.contracts import ModelAuth
from ai.types.events import AssistantMessageEvent
from ai.types.messages import TranscriptContext
from ai.types.model import Model
from ai.types.options import RequestOptions, SimpleOptions


class ApiAdapter(Protocol):
    id: str

    def stream(
        self,
        model: Model,
        context: TranscriptContext,
        auth: ModelAuth,
        options: RequestOptions,
    ) -> AsyncIterator[AssistantMessageEvent]: ...

    def stream_simple(
        self,
        model: Model,
        context: TranscriptContext,
        auth: ModelAuth,
        options: SimpleOptions,
    ) -> AsyncIterator[AssistantMessageEvent]: ...

    async def aclose(self) -> None: ...
