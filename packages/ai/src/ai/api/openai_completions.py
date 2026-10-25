"""OpenAI Chat Completions 协议，支持兼容服务通过类型化配置接入。"""

from dataclasses import dataclass
from typing import Literal

from ai.api._shared.messages import normalize_tool_id, transform_messages
from ai.api._shared.replay import fold_system
from ai.api._shared.sdk import SDKAdapter
from ai.types.messages import (
    AssistantMessage,
    ImageContent,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from ai.types.model import resolve_reasoning
from ai.types.options import RequestOptions, SimpleOptions


@dataclass(kw_only=True)
class CompletionsOptions(RequestOptions):
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class CompletionsCompat:
    max_tokens_field: str = "max_completion_tokens"
    reasoning_field: str = "reasoning_content"
    include_usage: bool = True
    strict_tools: bool = True
    # 兼容服务声明控制字段格式，适配器不按供应商名称分支。
    thinking_format: Literal["openai", "deepseek"] = "openai"


class OpenAICompletionsAdapter(SDKAdapter):
    id = "openai-completions"

    async def _generate(self, model, context, auth, options, accumulator):
        if (
            not isinstance(options, (SimpleOptions, CompletionsOptions))
            and type(options) is not RequestOptions
        ):
            raise TypeError("Options do not match openai-completions")
        compat = model.compat or CompletionsCompat()
        if not isinstance(compat, CompletionsCompat):
            raise TypeError("Model compat does not match openai-completions")
        messages = transform_messages(context.messages, model, normalize_tool_id)
        system, tools = fold_system(messages)
        payload = {
            "model": model.id,
            "stream": True,
            "messages": convert_messages(messages, system, compat),
        }
        if compat.include_usage:
            payload["stream_options"] = {"include_usage": True}
        temperature = getattr(options, "temperature", None)
        temperature = temperature if temperature is not None else model.defaults.temperature
        limit = getattr(
            options,
            "max_output_tokens" if isinstance(options, SimpleOptions) else "max_tokens",
            None,
        )
        limit = limit if limit is not None else model.defaults.max_output_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        if limit is not None:
            payload[compat.max_tokens_field] = limit
        reasoning = (
            resolve_reasoning(model, options.reasoning)
            if isinstance(options, SimpleOptions)
            else getattr(options, "reasoning_effort", None)
        )
        if isinstance(options, SimpleOptions) and reasoning is not None:
            if compat.thinking_format == "deepseek":
                payload["thinking"] = {"type": "disabled" if reasoning == "off" else "enabled"}
                if reasoning != "off":
                    payload["reasoning_effort"] = reasoning
            else:
                payload["reasoning_effort"] = "none" if reasoning == "off" else reasoning
        elif reasoning is not None:
            # 专用选项保留原生值，不将原生字符串解释成 Simple 的控制值。
            payload["reasoning_effort"] = reasoning
        if tools:
            if not model.supports_tools:
                raise ValueError("Model does not support tools")
            definitions = []
            for tool in tools:
                if tool.constraint_mode == "require" and not compat.strict_tools:
                    raise ValueError("Required tool constraints are not supported")
                function = {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
                if tool.constraint_mode != "off" and compat.strict_tools:
                    function["strict"] = True
                definitions.append({"type": "function", "function": function})
            payload["tools"] = definitions
        finish = None
        async with self._events(
            model,
            auth,
            options,
            payload,
            ("chat", "completions"),
            ("model", "messages"),
        ) as incoming:
            async for chunk in incoming:
                accumulator.message.response_id = chunk.get("id")
                usage = chunk.get("usage")
                if usage:
                    accumulator.message.usage = Usage(
                        input=usage.get("prompt_tokens"),
                        output=usage.get("completion_tokens"),
                        total=usage.get("total_tokens"),
                        cache_read=(usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                        reasoning=(usage.get("completion_tokens_details") or {}).get(
                            "reasoning_tokens"
                        ),
                    )
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta") or {}
                    thinking = delta.get(compat.reasoning_field)
                    if thinking:
                        for event in accumulator.append("thinking", ThinkingContent(), thinking):
                            yield event
                    if delta.get("content"):
                        for event in accumulator.text(delta["content"]):
                            yield event
                    if delta.get("refusal"):
                        for event in accumulator.append(
                            "refusal", TextContent(metadata={"refusal": True}), delta["refusal"]
                        ):
                            yield event
                    for call in delta.get("tool_calls", []):
                        key = ("tool", call["index"])
                        function = call.get("function") or {}
                        for event in accumulator.start(
                            key,
                            ToolCall(
                                call.get("id", ""),
                                function.get("name", ""),
                            ),
                        ):
                            yield event
                        block = accumulator.block(key)
                        if call.get("id"):
                            block.id = call["id"]
                        if function.get("name"):
                            block.name = function["name"]
                        for event in accumulator.append(key, block, function.get("arguments", "")):
                            yield event
                    if choice.get("finish_reason"):
                        reason = choice["finish_reason"]
                        if reason not in ("stop", "length", "tool_calls"):
                            raise ValueError(f"Unsuccessful finish reason: {reason}")
                        finish = {"length": "length", "tool_calls": "tool_use"}.get(reason, "stop")
        if finish is None:
            raise ValueError("Stream ended without a finish reason")
        for event in accumulator.finish(finish):
            yield event


def convert_messages(messages, system, compat):
    """转换 Chat Completions 角色与内容；系统指令发送当前有效状态。"""
    result = [{"role": "system", "content": system}] if system else []
    pending_images = []

    def flush_images():
        if pending_images:
            result.append({"role": "user", "content": list(pending_images)})
            pending_images.clear()

    for message in messages:
        if isinstance(message, (UserMessage, AssistantMessage)):
            flush_images()
        if isinstance(message, UserMessage):
            content = message.content
            if isinstance(content, list):
                content = [
                    {"type": "text", "text": b.text}
                    if isinstance(b, TextContent)
                    else {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{b.mime_type};base64,{b.data}",
                        },
                    }
                    for b in content
                ]
            result.append({"role": "user", "content": content})
        elif isinstance(message, AssistantMessage):
            item = {
                "role": "assistant",
                "content": "".join(
                    b.text
                    for b in message.content
                    if isinstance(b, TextContent) and not b.metadata.get("refusal")
                )
                or None,
            }
            refusal = "".join(
                b.text
                for b in message.content
                if isinstance(b, TextContent) and b.metadata.get("refusal")
            )
            if refusal:
                item["refusal"] = refusal
            calls = [b for b in message.content if isinstance(b, ToolCall)]
            thinking = "".join(
                b.thinking for b in message.content if isinstance(b, ThinkingContent)
            )
            if thinking:
                item[compat.reasoning_field] = thinking
            if calls:
                item["tool_calls"] = [
                    {
                        "id": b.id,
                        "type": "function",
                        "function": {
                            "name": b.name,
                            "arguments": b.arguments_json,
                        },
                    }
                    for b in calls
                ]
            result.append(item)
        elif isinstance(message, ToolResultMessage):
            content = message.content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, ImageContent):
                        pending_images.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{block.mime_type};base64,{block.data}",
                                },
                            }
                        )
                content = "\n".join(b.text for b in content if isinstance(b, TextContent))
            result.append(
                {"role": "tool", "tool_call_id": message.tool_call_id, "content": content}
            )
    flush_images()
    return result
