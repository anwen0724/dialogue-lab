"""Anthropic Messages 协议，认证与宿主会话无关。"""

import json
from dataclasses import dataclass, field

from ai.api._shared.messages import normalize_tool_id, transform_messages
from ai.api._shared.replay import fold_system
from ai.api._shared.sdk import SDKAdapter
from ai.types.messages import (
    AssistantMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from ai.types.model import map_reasoning
from ai.types.options import RequestOptions, SimpleOptions


@dataclass(kw_only=True)
class AnthropicOptions(RequestOptions):
    max_tokens: int | None = None
    temperature: float | None = None
    thinking_budget: int | None = None
    cache_system: bool = False


@dataclass(frozen=True)
class AnthropicCompat:
    adaptive_thinking: bool = False
    strict_tools: bool = False
    thinking_budgets: dict[str, int] = field(
        default_factory=lambda: {
            "minimal": 1024,
            "low": 2048,
            "medium": 8192,
            "high": 16384,
        }
    )


class AnthropicMessagesAdapter(SDKAdapter):
    id = "anthropic-messages"
    sdk = "anthropic"

    async def _generate(self, model, context, auth, options, accumulator):
        if (
            not isinstance(options, (SimpleOptions, AnthropicOptions))
            and type(options) is not RequestOptions
        ):
            raise TypeError("Options do not match anthropic-messages")
        compat = model.compat or AnthropicCompat()
        if not isinstance(compat, AnthropicCompat):
            raise TypeError("Model compat does not match anthropic-messages")
        messages = transform_messages(context.messages, model, normalize_tool_id)
        system, tools = fold_system(messages)
        limit = getattr(
            options,
            "max_output_tokens" if isinstance(options, SimpleOptions) else "max_tokens",
            None,
        )
        if limit is None:
            limit = model.defaults.max_output_tokens or model.max_output_tokens
        if limit is None:
            raise ValueError("Anthropic requires max_output_tokens or a model default")
        payload = {
            "model": model.id,
            "stream": True,
            "max_tokens": limit,
            "messages": convert_messages(messages),
        }
        if system:
            payload["system"] = (
                [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
                if getattr(options, "cache_system", False)
                else system
            )
        temperature = getattr(options, "temperature", None)
        temperature = temperature if temperature is not None else model.defaults.temperature
        if temperature is not None:
            payload["temperature"] = temperature
        budget = getattr(options, "thinking_budget", None)
        if isinstance(options, SimpleOptions):
            level = map_reasoning(model, options.reasoning)
            if level and compat.adaptive_thinking:
                payload["thinking"] = {"type": "adaptive"}
                payload["output_config"] = {"effort": level}
            elif level:
                if level not in compat.thinking_budgets:
                    raise ValueError("No declared thinking budget for this level")
                budget = min(compat.thinking_budgets[level], limit - 1024)
        if budget is not None:
            if budget < 1024 or budget >= limit:
                raise ValueError("Thinking budget must be at least 1024 and below max_tokens")
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
        if tools:
            if not model.supports_tools:
                raise ValueError("Model does not support tools")
            definitions = []
            for tool in tools:
                if tool.constraint_mode == "require" and not compat.strict_tools:
                    raise ValueError("Required tool constraints are not supported")
                definition = {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                }
                if tool.constraint_mode != "off" and compat.strict_tools:
                    definition["strict"] = True
                definitions.append(definition)
            payload["tools"] = definitions
        finish = None
        completed = False
        usage_fields = {}
        async with self._events(
            model, auth, options, payload, ("messages",), ("model", "messages", "max_tokens")
        ) as incoming:
            async for event in incoming:
                kind = event["type"]
                if kind == "message_start":
                    accumulator.message.response_id = event["message"]["id"]
                    usage_fields.update(event["message"].get("usage") or {})
                elif kind == "content_block_start":
                    block = event["content_block"]
                    if block["type"] == "text":
                        for output in accumulator.append(
                            event["index"], TextContent(), block.get("text", "")
                        ):
                            yield output
                    elif block["type"] in ("thinking", "redacted_thinking"):
                        metadata = {"signature": block.get("signature", "")}
                        if block["type"] == "redacted_thinking":
                            metadata = {"redacted": block["data"]}
                        for output in accumulator.append(
                            event["index"],
                            ThinkingContent(metadata=metadata),
                            block.get("thinking", ""),
                        ):
                            yield output
                    elif block["type"] == "tool_use":
                        initial = json.dumps(block["input"]) if block.get("input") else ""
                        for output in accumulator.start(
                            event["index"], ToolCall(block["id"], block["name"], initial)
                        ):
                            yield output
                elif kind == "content_block_delta":
                    delta = event["delta"]
                    if delta["type"] == "text_delta":
                        for output in accumulator.append(
                            event["index"], TextContent(), delta["text"]
                        ):
                            yield output
                    elif delta["type"] in ("thinking_delta", "input_json_delta"):
                        text = delta.get("thinking", delta.get("partial_json", ""))
                        for output in accumulator.append(
                            event["index"], accumulator.block(event["index"]), text
                        ):
                            yield output
                    elif delta["type"] == "signature_delta":
                        block = accumulator.block(event["index"])
                        block.metadata["signature"] = (
                            block.metadata.get("signature", "") + delta["signature"]
                        )
                elif kind == "content_block_stop":
                    block = accumulator.block(event["index"])
                    if isinstance(block, ToolCall) and not block.arguments_json:
                        block.arguments_json = "{}"
                    for output in accumulator.end(event["index"]):
                        yield output
                elif kind == "message_delta":
                    reason = event["delta"].get("stop_reason")
                    if reason:
                        finish = {"max_tokens": "length", "tool_use": "tool_use"}.get(
                            reason, "stop"
                        )
                    usage_fields.update(event.get("usage") or {})
                elif kind == "message_stop":
                    completed = True
                elif kind == "error":
                    raise ValueError(str(event.get("error")))
                update_usage(accumulator.message.usage, usage_fields)
        if not completed or finish is None:
            raise ValueError("Stream ended without message_stop and stop_reason")
        for output in accumulator.finish(finish):
            yield output


def update_usage(usage, values):
    """Anthropic 缓存读写不含在原 input_tokens 内，统一 input 只求和一次。"""
    usage.cache_read = values.get("cache_read_input_tokens")
    usage.cache_write = values.get("cache_creation_input_tokens")
    base = values.get("input_tokens")
    usage.input = (
        base + (usage.cache_read or 0) + (usage.cache_write or 0) if base is not None else None
    )
    usage.output = values.get("output_tokens")
    usage.reasoning = values.get("thinking_tokens")
    if usage.input is not None and usage.output is not None:
        usage.total = usage.input + usage.output


def input_content(content):
    if isinstance(content, str):
        return content
    return [
        {"type": "text", "text": b.text}
        if isinstance(b, TextContent)
        else {
            "type": "image",
            "source": {"type": "base64", "media_type": b.mime_type, "data": b.data},
        }
        for b in content
    ]


def convert_messages(messages):
    """把工具结果放在 user 内容块中，并重放有效的签名。"""
    result = []
    pending_images = []

    def append(role, content):
        if result and result[-1]["role"] == role:
            previous = result[-1]["content"]
            if isinstance(previous, str):
                previous = [{"type": "text", "text": previous}]
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            result[-1]["content"] = previous + content
        else:
            result.append({"role": role, "content": content})

    for message in messages:
        if isinstance(message, (UserMessage, AssistantMessage)) and pending_images:
            append("user", list(pending_images))
            pending_images.clear()
        if isinstance(message, UserMessage):
            append("user", input_content(message.content))
        elif isinstance(message, ToolResultMessage):
            content = input_content(message.content)
            if message.is_error and isinstance(content, list):
                images = [b for b in content if b["type"] == "image"]
                if images:
                    content = [b for b in content if b["type"] != "image"]
                    content.append(
                        {"type": "text", "text": "(image attached after the tool results)"}
                    )
                    pending_images.append(
                        {
                            "type": "text",
                            "text": (
                                f"Images from the error result of tool call "
                                f"{message.tool_call_id} ({message.name}):"
                            ),
                        }
                    )
                    pending_images.extend(images)
            append(
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id,
                        "content": content,
                        "is_error": message.is_error,
                    }
                ],
            )
        elif isinstance(message, AssistantMessage):
            content = []
            for block in message.content:
                if isinstance(block, TextContent):
                    content.append({"type": "text", "text": block.text})
                elif isinstance(block, ThinkingContent):
                    if "redacted" in block.metadata:
                        content.append(
                            {"type": "redacted_thinking", "data": block.metadata["redacted"]}
                        )
                    elif block.metadata.get("signature"):
                        content.append(
                            {
                                "type": "thinking",
                                "thinking": block.thinking,
                                "signature": block.metadata["signature"],
                            }
                        )
                elif isinstance(block, ToolCall):
                    content.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.arguments
                            if block.arguments is not None
                            else json.loads(block.arguments_json),
                        }
                    )
            if content:
                append("assistant", content)
    if pending_images:
        append("user", pending_images)
    return result
