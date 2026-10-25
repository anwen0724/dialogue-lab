"""工具参数校验与显式转换，不执行工具。"""

from collections.abc import Callable
from copy import deepcopy

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

from ai.errors import ToolValidationError
from ai.types.messages import Tool, ToolCall


def validate_tool_call(tool: Tool, call: ToolCall) -> dict:
    """严格校验并返回参数副本。"""
    if call.name != tool.name or call.arguments is None or call.arguments_error:
        raise ToolValidationError("Tool name or parsed arguments are invalid")
    try:
        Draft202012Validator.check_schema(tool.parameters)
        # 空 Registry 不执行网络读取；仅 Schema 内的本地引用可解析。
        Draft202012Validator(tool.parameters, registry=Registry()).validate(call.arguments)
    except (SchemaError, ValidationError, Unresolvable) as exc:
        raise ToolValidationError(getattr(exc, "message", str(exc))) from exc
    return deepcopy(call.arguments)


def convert_tool_call(tool: Tool, call: ToolCall, converter: Callable[[dict], dict]) -> ToolCall:
    """在副本上执行调用者给定规则，再严格校验转换结果。"""
    if call.arguments is None or call.arguments_error:
        raise ToolValidationError("Tool arguments are not complete JSON")
    converted = deepcopy(call)
    converted.arguments = converter(deepcopy(call.arguments))
    validate_tool_call(tool, converted)
    return converted
