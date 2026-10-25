from ai.serialization import message_from_dict, message_to_dict
from ai.types.messages import AssistantMessage, ThinkingContent, ToolCall, Usage


def test_round_trip_preserves_replay_metadata_and_raw_tool_arguments():
    original = AssistantMessage(
        provider="anthropic",
        model="custom",
        api="anthropic-messages",
        response_id="upstream-id",
        stop_reason="tool_use",
        content=[
            ThinkingContent("考虑", {"signature": "signed"}),
            ToolCall("call-1", "lookup", '{"n":2}', {"n": 2}),
        ],
        usage=Usage(input=12, output=7, total=19, cache_read=3),
    )

    encoded = message_to_dict(original)

    assert encoded["role"] == "assistant"
    assert "format_version" not in encoded
    assert encoded["content"][0]["metadata"] == {"signature": "signed"}
    assert message_from_dict(encoded) == original
    encoded["content"][0]["metadata"]["signature"] = "changed"
    assert original.content[0].metadata["signature"] == "signed"
