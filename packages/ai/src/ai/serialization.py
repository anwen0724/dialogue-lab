"""公开消息的字典编解码；不附加存储版本或访问数据库。"""

from copy import deepcopy
from dataclasses import asdict

from ai.errors import ErrorInfo
from ai.types.messages import (
    AssistantMessage,
    ImageContent,
    Message,
    SystemMessage,
    TextContent,
    ThinkingContent,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)


def message_to_dict(message: Message) -> dict:
    """输出独立的数据副本，包含角色、块类型和协议重放字段。"""
    return asdict(message)


def message_from_dict(value: dict) -> Message:
    """按公开判别字段恢复消息；未知类型明确失败。"""
    data = deepcopy(value)
    role = data.pop("role")
    if role == "system":
        data["tools_added"] = [Tool(**tool) for tool in data.get("tools_added", [])]
        return SystemMessage(**data)
    content = data.get("content", [])
    if isinstance(content, list):
        constructors = {
            "text": TextContent,
            "image": ImageContent,
            "thinking": ThinkingContent,
            "tool_call": ToolCall,
        }
        blocks = []
        for block in content:
            kind = block.pop("type")
            if kind not in constructors:
                raise ValueError(f"Unknown content type: {kind}")
            blocks.append(constructors[kind](**block))
        data["content"] = blocks
    if role == "assistant":
        data["usage"] = Usage(**data.get("usage", {}))
        if data.get("error") is not None:
            data["error"] = ErrorInfo(**data["error"])
        return AssistantMessage(**data)
    if role == "user":
        return UserMessage(**data)
    if role == "tool_result":
        return ToolResultMessage(**data)
    raise ValueError(f"Unknown message role: {role}")
