"""创建 HTTP 应用并装配 API 路由。"""

from fastapi import FastAPI

from dialogue_lab.api.health import router as health_router
from dialogue_lab.config import Settings


def create_app() -> FastAPI:
    """每个应用实例在创建时加载配置。"""
    settings = Settings()
    application = FastAPI(title=settings.app_name)
    application.include_router(health_router, prefix="/api")
    return application


app = create_app()
