"""测试供应商边界；应用仍使用真实 Models 和上下文转换。"""

from ai import AssistantMessage, AssistantMessageEvent, Model, Models, TextContent, create_provider
from ai.auth.api_key import ApiKeyAuth


class ScriptedAdapter:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.inputs = []

    async def stream_simple(self, model, context, auth, options):
        self.inputs.append(context)
        message = AssistantMessage(model.provider, model.id, model.api)
        yield AssistantMessageEvent("start", message)
        block = TextContent()
        message.content.append(block)
        for fragment in next(self.replies):
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
