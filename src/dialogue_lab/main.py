"""创建 HTTP 应用并装配 API 路由。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from dialogue_lab.api.health import router as health_router
from dialogue_lab.api.sessions import router as session_router
from dialogue_lab.api.voice import router as voice_router
from dialogue_lab.config import Settings
from dialogue_lab.sessions.service import SessionService
from dialogue_lab.sessions.types import SessionError
from dialogue_lab.storage.database import Database
from dialogue_lab.storage.session_store import SessionStore


def create_app() -> FastAPI:
    """每个应用实例在创建时加载配置。"""
    settings = Settings()

    @asynccontextmanager
    async def lifespan(application):
        database = Database(settings.database_url.get_secret_value())
        application.state.sessions = SessionService(SessionStore(database))
        try:
            yield
        finally:
            await database.close()

    application = FastAPI(title=settings.app_name, lifespan=lifespan)
    application.state.settings = settings
    application.include_router(health_router, prefix="/api")
    application.include_router(voice_router, prefix="/api")
    application.include_router(session_router, prefix="/api")

    @application.exception_handler(SessionError)
    async def session_error(request: Request, error: SessionError):
        return JSONResponse({"code": error.code, "message": str(error)}, status_code=error.status)

    return application


app = create_app()
