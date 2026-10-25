from ai.retry import retry_assistant_call
from ai.types.messages import AssistantMessage, TextContent


async def test_explicit_retry_returns_one_attempt_without_stitching_partial_output():
    results = iter(
        [
            AssistantMessage("p", "m", "a", [TextContent("partial")], stop_reason="error"),
            AssistantMessage("p", "m", "a", [TextContent("fresh")]),
        ]
    )

    async def generate():
        return next(results)

    result = await retry_assistant_call(
        generate,
        max_attempts=2,
        should_retry=lambda result, attempt: result.stop_reason == "error",
    )
    assert result.content == [TextContent("fresh")]
