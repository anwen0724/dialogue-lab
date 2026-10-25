"""请求扩展与只读诊断采用不同的数据契约。"""

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

type Hook = Callable[..., object | Awaitable[object]]


@dataclass(frozen=True)
class ResponseInfo:
    status: int
    headers: Mapping[str, str]


@dataclass(frozen=True)
class DiagnosticEvent:
    """诊断不携带正文、工具参数或凭据。elapsed 单位为秒。"""

    type: str
    elapsed: float
    provider: str
    model: str
    data: Mapping[str, object]


async def invoke(hook: Hook | None, *args):
    """在原请求路径等待扩展；同步或异步回调均不建立新消费者。"""
    if hook is None:
        return None
    result = hook(*args)
    return await result if inspect.isawaitable(result) else result


async def observe(observer: Hook | None, event: DiagnosticEvent) -> None:
    """诊断失败只报告类型，避免异常文本泄露请求材料。"""
    try:
        await invoke(observer, event)
    except Exception as exc:
        logging.getLogger(__name__).warning("AI observer failed: %s", type(exc).__name__)
