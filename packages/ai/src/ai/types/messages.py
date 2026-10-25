"""输入、输出消息和内容块，不含宿主业务身份。"""

from dataclasses import dataclass, field
from typing import Literal

from ai.errors import ErrorInfo

type StopReason = Literal["stop", "length", "tool_use", "error", "aborted"]


@dataclass
class TextContent:
    text: str = ""
    metadata: dict = field(default_factory=dict)
    type: Literal["text"] = field(default="text", init=False)


@dataclass
class ImageContent:
    mime_type: str
    data: str
    type: Literal["image"] = field(default="image", init=False)


@dataclass
class ThinkingContent:
    thinking: str = ""
    metadata: dict = field(default_factory=dict)
    type: Literal["thinking"] = field(default="thinking", init=False)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments_json: str = ""
    arguments: dict | None = None
    arguments_error: str | None = None
    metadata: dict = field(default_factory=dict)
    type: Literal["tool_call"] = field(default="tool_call", init=False)


@dataclass
class Tool:
    """工具声明只描述输入，不保存执行函数。"""

    name: str
    description: str
    parameters: dict
    constraint_mode: Literal["off", "prefer", "require"] = "off"


@dataclass
class Usage:
    """缓存、推理为供应商用量子集时不重复累加到 total。"""

    input: int | None = None
    output: int | None = None
    total: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None
    reasoning: int | None = None


@dataclass
class SystemMessage:
    content: str = ""
    sections: dict[str, str | None] = field(default_factory=dict)
    tools_added: list[Tool] = field(default_factory=list)
    tools_removed: list[str] = field(default_factory=list)
    role: Literal["system"] = field(default="system", init=False)


@dataclass
class UserMessage:
    content: str | list[TextContent | ImageContent]
    role: Literal["user"] = field(default="user", init=False)


@dataclass
class AssistantMessage:
    provider: str
    model: str
    api: str
    content: list[TextContent | ThinkingContent | ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    stop_reason: StopReason = "stop"
    response_id: str | None = None
    error: ErrorInfo | None = None
    role: Literal["assistant"] = field(default="assistant", init=False)


@dataclass
class ToolResultMessage:
    tool_call_id: str
    name: str
    content: str | list[TextContent | ImageContent]
    is_error: bool = False
    role: Literal["tool_result"] = field(default="tool_result", init=False)


type Message = SystemMessage | UserMessage | AssistantMessage | ToolResultMessage


@dataclass
class Context:
    system_prompt: str = ""
    messages: list[Message] = field(default_factory=list)
    tools: list[Tool] = field(default_factory=list)


@dataclass
class TranscriptContext:
    messages: list[Message] = field(default_factory=list)
