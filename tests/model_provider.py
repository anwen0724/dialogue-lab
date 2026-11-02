"""测试供应商边界；应用仍使用真实 Models 和上下文转换。"""

from ai import (
    AssistantMessage,
    AssistantMessageEvent,
    Model,
    Models,
    TextContent,
    ToolCall,
    create_provider,
)
from ai.auth.api_key import ApiKeyAuth


class ScriptedAdapter:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.inputs = []
        self.calls = []

    async def stream_simple(self, model, context, auth, options):
        self.inputs.append(context)
        self.calls.append((model, auth, options))
        message = AssistantMessage(model.provider, model.id, model.api)
        yield AssistantMessageEvent("start", message)
        reply = next(self.replies)
        if reply and isinstance(reply[0], ToolCall):
            message.content.extend(reply)
            message.stop_reason = "tool_use"
            yield AssistantMessageEvent("done", message)
            return
        block = TextContent()
        message.content.append(block)
        for fragment in reply:
            block.text += fragment
            yield AssistantMessageEvent("text_delta", message, 0, fragment)
        yield AssistantMessageEvent("done", message)

    async def aclose(self):
        pass


def test_models(adapter):
    model = Model("test", "dialogue", "test", "", context_window=100000)
    models = Models()
    models.set_provider(
        create_provider(
            "test", models=[model], auth=ApiKeyAuth(keyless=True), adapters={"test": adapter}
        ),
        owns_provider=True,
    )
    return models, model
