import pytest

from ai.errors import ToolValidationError
from ai.tools import convert_tool_call, validate_tool_call
from ai.types.messages import Tool, ToolCall


def test_strict_validation_accepts_matching_values_and_does_not_coerce_strings():
    tool = Tool(
        "count",
        "计数",
        {
            "type": "object",
            "properties": {"n": {"type": "integer"}},
            "required": ["n"],
        },
    )
    valid = ToolCall("1", "count", '{"n":2}', {"n": 2})
    assert validate_tool_call(tool, valid) == {"n": 2}

    invalid = ToolCall("2", "count", '{"n":"2"}', {"n": "2"})
    with pytest.raises(ToolValidationError):
        validate_tool_call(tool, invalid)
    assert invalid.arguments == {"n": "2"}


def test_explicit_conversion_preserves_original_and_validates_result():
    tool = Tool(
        "count",
        "计数",
        {
            "type": "object",
            "properties": {"n": {"type": "integer"}},
            "required": ["n"],
        },
    )
    original = ToolCall("1", "count", '{"n":"2"}', {"n": "2"})

    def declared_rule(arguments):
        arguments["n"] = int(arguments["n"])
        return arguments

    converted = convert_tool_call(tool, original, declared_rule)
    assert converted.arguments == {"n": 2}
    assert converted.arguments_json == original.arguments_json
    assert original.arguments == {"n": "2"}
    with pytest.raises(ToolValidationError):
        convert_tool_call(tool, original, lambda args: {"n": None})


def test_local_schema_reference_failure_uses_tool_validation_error():
    tool = Tool(
        "tool", "tool", {"type": "object", "properties": {"x": {"$ref": "#/$defs/missing"}}}
    )
    with pytest.raises(ToolValidationError):
        validate_tool_call(tool, ToolCall("c", "tool", '{"x":1}', {"x": 1}))
