"""HTTP 会话入口；不在路由中组织上下文或执行模型。"""

from fastapi import APIRouter, Request

from dialogue_lab.sessions.types import SessionCreate

router = APIRouter()


@router.post("/sessions", status_code=201)
async def create_session(body: SessionCreate, request: Request):
    return await request.app.state.sessions.create(body.title)


@router.get("/sessions/{session_id}")
async def get_session(session_id: int, request: Request):
    return await request.app.state.sessions.open(session_id)


@router.get("/sessions")
async def list_sessions(request: Request):
    return await request.app.state.sessions.list()


@router.get("/presets")
async def list_presets(request: Request):
    return request.app.state.services.prompts.list()
