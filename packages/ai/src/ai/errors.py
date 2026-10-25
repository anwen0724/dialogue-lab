"""公开使用错误与请求错误描述。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorInfo:
    """可保存的错误信息，不持有 SDK 异常或请求对象。"""

    code: str
    message: str
    http_status: int | None = None
    provider_request_id: str | None = None
    retryable: bool = False


class AIError(Exception):
    """调用契约不满足时抛出的异常。"""


class ToolValidationError(AIError):
    """工具参数不满足工具 Schema。"""


class MissingDependencyError(AIError):
    """所选协议的可选依赖未安装。"""


def error_from_exception(exc: Exception) -> ErrorInfo:
    """通过 SDK 的公开异常字段提取普通数据，不向上层泄漏 SDK 对象。"""
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    details = body.get("error", body) if isinstance(body, dict) else {}
    details = details if isinstance(details, dict) else {}
    code = details.get("code") or details.get("type") or "request_error"
    if "Timeout" in type(exc).__name__ or isinstance(exc, TimeoutError):
        code = "timeout"
    quota = code in ("insufficient_quota", "billing_hard_limit_reached")
    retryable = status in (429, 502, 503, 504) and not quota
    if type(exc).__name__ in ("APIConnectionError", "ConnectError", "ConnectTimeout"):
        retryable = True
    return ErrorInfo(
        str(code),
        str(exc),
        status,
        getattr(exc, "request_id", None),
        retryable,
    )
