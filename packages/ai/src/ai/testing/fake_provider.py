"""固定文字及可控释放时点的测试 Provider。"""

import asyncio

from ai.auth.api_key import ApiKeyAuth
from ai.types.events import AssistantMessageEvent
from ai.types.messages import AssistantMessage, TextContent


class FakeProvider:
    """用于宿主联调；gate 控制开始输出，started 表示已经进入生成。"""

    def __init__(self, text="hello", *, id="fake", models=(), gate=None):
        self.id = id
        self.auth = ApiKeyAuth(keyless=True)
        self.text = text
        self._models = tuple(models)
        self.gate = gate
        self.started = asyncio.Event()
        self.closed = False
        self.released = asyncio.Event()

    def get_models(self):
        return self._models

    async def stream(self, model, context, auth, options):
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        message = AssistantMessage(model.provider, model.id, model.api)
        yield AssistantMessageEvent("start", message)
        message.content.append(TextContent())
        yield AssistantMessageEvent("text_start", message, 0)
        for part in self.text:
            message.content[0].text += part
            yield AssistantMessageEvent("text_delta", message, 0, part)
        yield AssistantMessageEvent("text_end", message, 0)
        yield AssistantMessageEvent("done", message)

    def stream_simple(self, model, context, auth, options):
        return self.stream(model, context, auth, options)

    async def aclose(self):
        self.closed = True
        self.released.set()
