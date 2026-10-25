"""无需 SDK、密钥或宿主业务组件的完整调用示例。"""

import asyncio

from ai import Context, Model, Models, UserMessage
from ai.testing.fake_provider import FakeProvider


async def main():
    model = Model("fake", "example", "fake", "http://unused")
    async with Models() as models:
        models.set_provider(FakeProvider("独立 AI 层可以使用。"), owns_provider=True)
        stream = models.stream_simple(model, Context(messages=[UserMessage("你好")]))
        async for event in stream:
            if event.type == "text_delta":
                print(event.delta, end="", flush=True)
        message = await stream.result()
        print(f"\nstop_reason={message.stop_reason}")


if __name__ == "__main__":
    asyncio.run(main())
