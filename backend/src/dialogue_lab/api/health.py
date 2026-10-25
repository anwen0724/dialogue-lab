"""提供服务存活检查，不探测外部依赖。"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """健康接口的公开响应。"""

    status: Literal["ok"] = "ok"


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """应用能够响应请求时，返回存活状态。"""
    return HealthResponse()
