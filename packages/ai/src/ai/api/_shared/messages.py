"""构造发送视图：图片降级、跨模型重放和工具配对。"""

import hashlib
import re
from copy import deepcopy

from ai.types.messages import (
    AssistantMessage,
    ImageContent,
    SystemMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


def transform_messages(messages, model, normalize_id=lambda value: value):
    """只修改副本；系统变化不提前结束工具结果组。"""
    transformed = deepcopy(messages)
    id_map = {}
    for message in transformed:
        if isinstance(message, (UserMessage, ToolResultMessage)):
            if "image" not in model.input_modalities and isinstance(message.content, list):
                label = "tool image" if isinstance(message, ToolResultMessage) else "image"
                placeholder = f"({label} omitted: model does not support images)"
                replaced = []
                for block in message.content:
                    if isinstance(block, ImageContent):
                        if not replaced or replaced[-1] != TextContent(placeholder):
                            replaced.append(TextContent(placeholder))
                    else:
                        replaced.append(block)
                message.content = replaced
        if isinstance(message, ToolResultMessage):
            message.tool_call_id = id_map.get(message.tool_call_id, message.tool_call_id)
        if isinstance(message, AssistantMessage):
            same = (message.provider, message.model, message.api) == (
                model.provider,
                model.id,
                model.api,
            )
            if not same:
                message.content = [b for b in message.content if not isinstance(b, ThinkingContent)]
                for block in message.content:
                    block.metadata = {}
                    if isinstance(block, ToolCall):
                        new_id = normalize_id(block.id)
                        id_map[block.id] = new_id
                        block.id = new_id

    result, pending, held_system = [], [], []
    answered = set()

    def flush():
        for call in pending:
            if call.id not in answered:
                result.append(
                    ToolResultMessage(
                        call.id,
                        call.name,
                        "No result provided",
                        is_error=True,
                    )
                )
        result.extend(held_system)
        pending.clear()
        answered.clear()
        held_system.clear()

    for message in transformed:
        if isinstance(message, (UserMessage, AssistantMessage)):
            flush()
        if isinstance(message, AssistantMessage):
            if message.stop_reason in ("error", "aborted"):
                continue
            pending.extend(b for b in message.content if isinstance(b, ToolCall))
        if isinstance(message, ToolResultMessage):
            answered.add(message.tool_call_id)
        if isinstance(message, SystemMessage) and pending:
            held_system.append(message)
        else:
            result.append(message)
    flush()
    return result


def normalize_tool_id(value):
    """转换跨协议 ID，并保留稳定摘要避免截断后的关联碰撞。"""
    if re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value):
        return value
    prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", value)[:48]
    return prefix + "_" + hashlib.sha256(value.encode()).hexdigest()[:15]
