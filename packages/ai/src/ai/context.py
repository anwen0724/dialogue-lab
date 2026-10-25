"""把便捷 Context 规范化为只有消息序列的输入。"""

from copy import deepcopy

from ai.types.messages import Context, SystemMessage, TranscriptContext


def normalize_context(context: Context | TranscriptContext) -> TranscriptContext:
    """不选择、重排或修改宿主提供的内容。"""
    if not isinstance(context, (Context, TranscriptContext)):
        raise TypeError("context must be Context or TranscriptContext")
    messages = deepcopy(context.messages)
    if isinstance(context, Context) and (context.system_prompt or context.tools):
        messages.insert(
            0,
            SystemMessage(
                content=context.system_prompt,
                tools_added=deepcopy(context.tools),
            ),
        )
    return TranscriptContext(messages)
