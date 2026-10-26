from ai.context import normalize_context
from ai.types.messages import Context, SystemMessage, Tool, UserMessage


def test_convenience_fields_become_a_leading_system_message_without_changing_input():
    tool = Tool("lookup", "查找", {"type": "object"})
    user = UserMessage("你好")
    explicit = SystemMessage(content="保留这条调用方提供的系统消息")
    original = Context(system_prompt="简短回答", messages=[explicit, user], tools=[tool])

    transcript = normalize_context(original)

    assert transcript.messages == [
        SystemMessage(content="简短回答", tools_added=[tool]),
        explicit,
        user,
    ]
    assert original.messages == [explicit, user]
    assert original.tools == [tool]
