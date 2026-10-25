"""主动生产的事件队列；result 等待不消费事件。"""

import asyncio

from ai.types.events import AssistantMessageEvent
from ai.types.messages import AssistantMessage


class AssistantMessageStream:
    """对外只提供异步迭代和结果等待，取消由请求 signal 控制。"""

    def __init__(self):
        self._events = asyncio.Queue()
        self._result = asyncio.get_running_loop().create_future()

    def __aiter__(self):
        return self

    async def __anext__(self) -> AssistantMessageEvent:
        event = await self._events.get()
        if event is None:
            # 终止标记留给同一队列的其他竞争迭代器。
            self._events.put_nowait(None)
            raise StopAsyncIteration
        return event

    async def result(self) -> AssistantMessage:
        return await asyncio.shield(self._result)

    def _push(self, event: AssistantMessageEvent) -> None:
        if self._result.done():
            return
        self._events.put_nowait(event)
        if event.type in ("done", "error"):
            self._result.set_result(event.partial)
            self._events.put_nowait(None)
