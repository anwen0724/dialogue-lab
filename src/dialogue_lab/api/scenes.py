"""场景资料接口，图片与身份文档均由服务端管理。"""

import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from dialogue_lab.scenes.images import MAX_IMAGE_BYTES
from dialogue_lab.scenes.types import SceneCreate, SceneUpdate
from dialogue_lab.sessions.types import SessionError

router = APIRouter()


@router.get("/scenes")
async def list_scenes(request: Request):
    return await request.app.state.services.scenes.list()


@router.post("/scenes", status_code=201)
async def create_scene(body: SceneCreate, request: Request):
    return await request.app.state.services.scenes.save(body.model_dump())


@router.get("/scenes/{scene_id}")
async def get_scene(scene_id: int, request: Request):
    return await request.app.state.services.scenes.get(scene_id)


@router.patch("/scenes/{scene_id}")
async def update_scene(scene_id: int, body: SceneUpdate, request: Request):
    return await request.app.state.services.scenes.save(
        body.model_dump(exclude_none=True), scene_id
    )


@router.delete("/scenes/{scene_id}")
async def delete_scene(scene_id: int, request: Request):
    status = await request.app.state.services.scenes.delete(scene_id)
    return {"status": status}


@router.post("/scenes/{scene_id}/images/{kind}")
async def upload_image(scene_id: int, kind: Literal["cover", "background"], request: Request):
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_IMAGE_BYTES:
            raise SessionError("IMAGE_TOO_LARGE", "图片不能超过 10 MB。", 413)
        content.extend(chunk)
    return await request.app.state.services.scenes.upload(scene_id, kind, bytes(content))


@router.get("/media/{name}")
async def get_image(name: str, request: Request):
    if not re.fullmatch(r"[a-f0-9]{32}\.(jpg|png|webp)", name):
        raise SessionError("IMAGE_NOT_FOUND", "图片不存在。", 404)
    path = request.app.state.settings.data_directory / "images" / name
    if not path.is_file():
        raise SessionError("IMAGE_NOT_FOUND", "图片不存在。", 404)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/scene-assets/{name}")
async def get_scene_asset(name: Literal["cafe.png", "studio.jpg", "night.jpg"]):
    return FileResponse(Path(__file__).resolve().parents[1] / "resources" / "images" / name)
