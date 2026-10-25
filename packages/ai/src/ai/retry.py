"""显式整次调用重试，不重放工具、不拼接部分输出。"""

from ai.hooks import invoke


async def retry_assistant_call(call, *, max_attempts, should_retry):
    """attempt 从 1 计数；失败消息由宿主判断，抛出的使用错误不重试。"""
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    for attempt in range(1, max_attempts + 1):
        result = await call()
        if attempt == max_attempts or not await invoke(should_retry, result, attempt):
            return result
