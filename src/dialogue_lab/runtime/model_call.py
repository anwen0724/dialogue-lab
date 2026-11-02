"""执行一次模型调用并交付正文增量及结束结果，不访问数据库。"""

from copy import deepcopy
from dataclasses import replace

from ai import Context


async def call_model(models, model, context: Context, options, emit):
    """仅交付正文；思考和工具参数留在最终消息，不送到语音通道。"""
    stream = models.stream_simple(model, context, options)
    draft = None
    async for event in stream:
        if event.type not in ("done", "error"):
            draft = event.partial
        if event.type == "text_delta":
            await emit({"type": "text_delta", "text": event.delta})
    result = await stream.result()
    # AI 调用层在外层取消时可能返回空终态；宿主保留已经收到的草稿。
    if result.stop_reason in ("aborted", "error") and not result.content and draft is not None:
        result = replace(result, content=deepcopy(draft.content), usage=deepcopy(draft.usage))
    return result
