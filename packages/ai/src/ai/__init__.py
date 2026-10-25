"""独立 AI 调用层；根入口不加载任何供应商 SDK。"""

from ai.auth.contracts import AuthContext, AuthResolver, CredentialStore, ModelAuth
from ai.auth.memory import MemoryCredentialStore
from ai.context import normalize_context
from ai.errors import AIError, ErrorInfo, MissingDependencyError, ToolValidationError
from ai.models import Models
from ai.provider import Provider, create_provider
from ai.retry import retry_assistant_call
from ai.serialization import message_from_dict, message_to_dict
from ai.stream import AssistantMessageStream
from ai.tools import convert_tool_call, validate_tool_call
from ai.types.events import AssistantMessageEvent
from ai.types.messages import (
    AssistantMessage,
    Context,
    ImageContent,
    SystemMessage,
    TextContent,
    ThinkingContent,
    Tool,
    ToolCall,
    ToolResultMessage,
    TranscriptContext,
    Usage,
    UserMessage,
)
from ai.types.model import Model, ModelCost, ModelDefaults
from ai.types.options import AbortController, AbortSignal, RequestOptions, SimpleOptions

__all__ = [
    "AIError",
    "AbortController",
    "AbortSignal",
    "AssistantMessage",
    "AssistantMessageEvent",
    "AssistantMessageStream",
    "AuthContext",
    "AuthResolver",
    "Context",
    "CredentialStore",
    "ErrorInfo",
    "ImageContent",
    "MemoryCredentialStore",
    "MissingDependencyError",
    "Model",
    "ModelAuth",
    "ModelCost",
    "ModelDefaults",
    "Models",
    "Provider",
    "RequestOptions",
    "SimpleOptions",
    "SystemMessage",
    "TextContent",
    "ThinkingContent",
    "Tool",
    "ToolCall",
    "ToolResultMessage",
    "ToolValidationError",
    "TranscriptContext",
    "Usage",
    "UserMessage",
    "convert_tool_call",
    "create_provider",
    "message_from_dict",
    "message_to_dict",
    "normalize_context",
    "retry_assistant_call",
    "validate_tool_call",
]
