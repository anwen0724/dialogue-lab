"""取消信号仅中断所属生成任务，不触碰共享客户端。"""

import asyncio
from contextlib import asynccontextmanager


@asynccontextmanager
async def closing_iterator(iterator):
    """在转发端退出时关闭支持 aclose 的来源，不要求扩展者继承生成器。"""
    try:
        yield iterator
    finally:
        close = getattr(iterator, "aclose", None)
        if close is not None:
            await close()


async def cancel_on_signal(task, signal):
    """信号到达后取消生成协程，让适配器执行自己的 finally 清理。"""
    await signal.wait()
    task.cancel()


async def close_all(resources):
    """所有关闭都执行，再报告实际失败；不自动重试关闭。"""
    results = await asyncio.gather(
        *(resource.aclose() for resource in resources), return_exceptions=True
    )
    errors = [result for result in results if isinstance(result, BaseException)]
    if errors:
        raise BaseExceptionGroup("AI resource cleanup failed", errors)
