"""只重试请求建立阶段，成功响应体不在这个循环内。"""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from ai.errors import error_from_exception
from ai.hooks import ResponseInfo, invoke


def retry_delay(exc, attempt):
    """遵守 Retry-After；没有服务指示时使用有上限的指数等待。"""
    response = getattr(exc, "response", None)
    value = response.headers.get("retry-after") if response is not None else None
    if value is not None:
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                return max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError):
                pass
    return min(2**attempt, 8)


@asynccontextmanager
async def open_response(factory, max_retries, on_response=None):
    """factory 每次创建新的 SDK 响应上下文；流开始后不重试。"""
    if max_retries < 0:
        raise ValueError("max_retries cannot be negative")
    for attempt in range(max_retries + 1):
        manager = factory()
        try:
            response = await manager.__aenter__()
            break
        except Exception as exc:
            failed_response = getattr(exc, "response", None)
            if failed_response is not None:
                try:
                    await invoke(
                        on_response,
                        ResponseInfo(failed_response.status_code, dict(failed_response.headers)),
                    )
                finally:
                    await failed_response.aclose()
            info = error_from_exception(exc)
            # SDK 的 APIConnectionError 也可能包裹发送后断线，只有连接失败才重试。
            retryable = info.retryable
            if type(exc).__name__ == "APIConnectionError":
                retryable = type(exc.__cause__).__name__ in ("ConnectError", "ConnectTimeout")
            if attempt == max_retries or not retryable:
                raise
            await asyncio.sleep(retry_delay(exc, attempt))
    try:
        await invoke(on_response, ResponseInfo(response.status_code, dict(response.headers)))
        yield response
    finally:
        await manager.__aexit__(None, None, None)
