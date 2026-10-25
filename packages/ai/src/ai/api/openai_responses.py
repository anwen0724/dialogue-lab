"""OpenAI Responses 的独立协议适配器。"""

from dataclasses import dataclass

from ai.api._shared.messages import transform_messages
from ai.api._shared.replay import fold_system
from ai.api._shared.sdk import SDKAdapter
from ai.types.messages import (
    AssistantMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from ai.types.model import map_reasoning
from ai.types.options import RequestOptions, SimpleOptions


@dataclass(kw_only=True)
class ResponsesOptions(RequestOptions):
    temperature: float | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    reasoning_summary: str | None = None
    store: bool = False


class OpenAIResponsesAdapter(SDKAdapter):
    id = "openai-responses"

    async def _generate(self, model, context, auth, options, accumulator):
        if (
            not isinstance(options, (SimpleOptions, ResponsesOptions))
            and type(options) is not RequestOptions
        ):
            raise TypeError("Options do not match openai-responses")
        messages = transform_messages(context.messages, model)
        system, tools = fold_system(messages)
        payload = {
            "model": model.id,
            "stream": True,
            "store": getattr(options, "store", False),
            "input": convert_messages(messages),
            "include": ["reasoning.encrypted_content"],
        }
        if system:
            payload["instructions"] = system
        if tools:
            if not model.supports_tools:
                raise ValueError("Model does not support tools")
            payload["tools"] = [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                    "strict": tool.constraint_mode != "off",
                }
                for tool in tools
            ]
        for name in ("temperature", "max_output_tokens"):
            value = getattr(options, name, None)
            value = value if value is not None else getattr(model.defaults, name)
            if value is not None:
                payload[name] = value
        reasoning = (
            map_reasoning(model, options.reasoning)
            if isinstance(options, SimpleOptions)
            else getattr(options, "reasoning_effort", None)
        )
        if reasoning:
            payload["reasoning"] = {"effort": reasoning}
        summary = getattr(options, "reasoning_summary", None)
        if summary:
            payload.setdefault("reasoning", {})["summary"] = summary
        finish = None
        async with self._events(
            model, auth, options, payload, ("responses",), ("model",)
        ) as incoming:
            async for event in incoming:
                kind = event["type"]
                if kind == "response.created":
                    accumulator.message.response_id = event["response"]["id"]
                elif kind in ("response.output_item.added", "response.output_item.done"):
                    item = event["item"]
                    key = event["output_index"]
                    block = None
                    if item["type"] == "function_call":
                        block = ToolCall(
                            item["call_id"], item["name"], metadata={"item_id": item["id"]}
                        )
                    elif item["type"] == "reasoning":
                        block = ThinkingContent(metadata={"item": item})
                    elif item["type"] == "message":
                        for text in accumulator.message.content:
                            if isinstance(text, TextContent) and text.metadata.get(
                                "item_id"
                            ) == item.get("id"):
                                if "phase" in item:
                                    text.metadata["phase"] = item["phase"]
                    if block is not None:
                        for output in accumulator.start(key, block):
                            yield output
                        current = accumulator.block(key)
                        if isinstance(current, ThinkingContent):
                            current.metadata["item"] = item
                        if kind == "response.output_item.done":
                            if isinstance(current, ToolCall):
                                current.arguments_json = item["arguments"]
                            for output in accumulator.end(key):
                                yield output
                elif kind == "response.function_call_arguments.delta":
                    key = event["output_index"]
                    for output in accumulator.append(key, accumulator.block(key), event["delta"]):
                        yield output
                elif kind == "response.reasoning_summary_text.delta":
                    for output in accumulator.append(
                        event["output_index"], ThinkingContent(), event["delta"]
                    ):
                        yield output
                elif kind in ("response.output_text.delta", "response.refusal.delta"):
                    key = ("text", event["output_index"], event["content_index"])
                    block = TextContent(
                        metadata={
                            "item_id": event.get("item_id"),
                            "content_index": event["content_index"],
                        }
                    )
                    if kind == "response.refusal.delta":
                        block.metadata["refusal"] = True
                    for item in accumulator.append(key, block, event["delta"]):
                        yield item
                elif kind == "response.content_part.done" and event["part"]["type"] in (
                    "output_text",
                    "refusal",
                ):
                    key = ("text", event["output_index"], event["content_index"])
                    refused = event["part"]["type"] == "refusal"
                    for item in accumulator.start(
                        key,
                        TextContent(
                            event["part"]["refusal" if refused else "text"],
                            {
                                "item_id": event.get("item_id"),
                                "content_index": event["content_index"],
                                "refusal": refused,
                            },
                        ),
                    ):
                        yield item
                    accumulator.block(key).metadata["annotations"] = event["part"].get(
                        "annotations", []
                    )
                elif kind in ("response.completed", "response.incomplete"):
                    response = event["response"]
                    accumulator.message.response_id = response["id"]
                    usage = response.get("usage") or {}
                    accumulator.message.usage = Usage(
                        input=usage.get("input_tokens"),
                        output=usage.get("output_tokens"),
                        total=usage.get("total_tokens"),
                        cache_read=(usage.get("input_tokens_details") or {}).get("cached_tokens"),
                        reasoning=(usage.get("output_tokens_details") or {}).get(
                            "reasoning_tokens"
                        ),
                    )
                    if kind == "response.incomplete":
                        reason = (response.get("incomplete_details") or {}).get("reason")
                        if reason != "max_output_tokens":
                            raise ValueError(f"Incomplete response: {reason}")
                    finish = (
                        "length"
                        if kind == "response.incomplete"
                        else (
                            "tool_use"
                            if any(isinstance(b, ToolCall) for b in accumulator.message.content)
                            else "stop"
                        )
                    )
                elif kind in ("response.failed", "error"):
                    raise ValueError(
                        str(event.get("error") or event.get("response", {}).get("error"))
                    )
        if finish is None:
            raise ValueError("Stream ended without a response terminal event")
        for item in accumulator.finish(finish):
            yield item


def convert_content(content):
    """Responses 用户和工具输出使用 input_text / input_image。"""
    if isinstance(content, str):
        return content
    return [
        {"type": "input_text", "text": block.text}
        if isinstance(block, TextContent)
        else {"type": "input_image", "image_url": f"data:{block.mime_type};base64,{block.data}"}
        for block in content
    ]


def convert_messages(messages):
    """签名和专用 item 仅在共享转换确认同模型之后重放。"""
    result = []
    for message in messages:
        if isinstance(message, UserMessage):
            result.append({"role": "user", "content": convert_content(message.content)})
        elif isinstance(message, ToolResultMessage):
            result.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": convert_content(message.content),
                }
            )
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextContent):
                    item_id = block.metadata.get("item_id")
                    part = {
                        "type": "output_text",
                        "text": block.text,
                        "annotations": block.metadata.get("annotations", []),
                    }
                    if block.metadata.get("refusal"):
                        part = {"type": "refusal", "refusal": block.text}
                    if item_id and result and result[-1].get("id") == item_id:
                        result[-1]["content"].append(part)
                    else:
                        item = {"type": "message", "role": "assistant", "content": [part]}
                        if item_id:
                            item["id"] = item_id
                        if "phase" in block.metadata:
                            item["phase"] = block.metadata["phase"]
                        result.append(item)
                elif isinstance(block, ThinkingContent) and "item" in block.metadata:
                    result.append(block.metadata["item"])
                elif isinstance(block, ToolCall):
                    item = {
                        "type": "function_call",
                        "call_id": block.id,
                        "name": block.name,
                        "arguments": block.arguments_json,
                    }
                    if "item_id" in block.metadata:
                        item["id"] = block.metadata["item_id"]
                    result.append(item)
    return result
