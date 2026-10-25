"""协议解析共用的活动消息累积器。"""

import json

from ai.types.events import AssistantMessageEvent
from ai.types.messages import AssistantMessage, TextContent, ThinkingContent, ToolCall


class Accumulator:
    """保持所有 partial 指向同一消息，协议决定块和终态语义。"""

    def __init__(self, model):
        self.message = AssistantMessage(model.provider, model.id, model.api)
        self._indices = {}
        self._ended = set()

    def event(self, kind, index=None, delta=""):
        return AssistantMessageEvent(kind, self.message, index, delta)

    def text(self, delta):
        return self.append("text", TextContent(), delta)

    def append(self, key, block, delta=""):
        """上游块标识映射到连续的公开 content_index。"""
        events = self.start(key, block)
        index = self._indices[key]
        block = self.message.content[index]
        if isinstance(block, TextContent):
            block.text += delta
        elif isinstance(block, ThinkingContent):
            block.thinking += delta
        else:
            block.arguments_json += delta
        if delta:
            events.append(self.event(f"{self._kind(block)}_delta", index, delta))
        return events

    def start(self, key, block):
        if key in self._indices:
            return []
        index = len(self.message.content)
        self._indices[key] = index
        self.message.content.append(block)
        return [self.event(f"{self._kind(block)}_start", index)]

    def block(self, key):
        return self.message.content[self._indices[key]]

    @staticmethod
    def _kind(block):
        return "toolcall" if isinstance(block, ToolCall) else block.type

    def end(self, key):
        if key in self._ended:
            return []
        self._ended.add(key)
        block = self.block(key)
        if isinstance(block, ToolCall):
            try:
                arguments = json.loads(block.arguments_json)
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be a JSON object")
                block.arguments = arguments
            except (ValueError, TypeError) as exc:
                block.arguments = None
                block.arguments_error = str(exc)
        return [self.event(f"{self._kind(block)}_end", self._indices[key])]

    def finish(self, reason):
        self.message.stop_reason = reason
        for key in self._indices:
            yield from self.end(key)
        yield self.event("done")

    def fail(self, error, *, aborted=False):
        """失败仍保留已接收内容，并标出未完成的工具 JSON。"""
        for key in self._indices:
            self.end(key)
        self.message.error = error
        self.message.stop_reason = "aborted" if aborted else "error"
        return self.event("error")
