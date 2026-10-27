"""角色资料接口，图片与身份文档均由服务端管理。"""

import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from dialogue_lab.characters.images import MAX_IMAGE_BYTES
from dialogue_lab.characters.types import CharacterCreate, CharacterUpdate
from dialogue_lab.sessions.types import SessionError

router = APIRouter()


@router.get("/characters")
async def list_characters(request: Request):
    return await request.app.state.services.characters.list()


@router.post("/characters", status_code=201)
async def create_character(body: CharacterCreate, request: Request):
    return await request.app.state.services.characters.save(body.model_dump())


@router.get("/characters/{character_id}")
async def get_character(character_id: int, request: Request):
    return await request.app.state.services.characters.get(character_id)


@router.post("/characters/{character_id}/copy", status_code=201)
async def copy_character(character_id: int, request: Request):
    return await request.app.state.services.characters.copy(character_id)


@router.patch("/characters/{character_id}")
async def update_character(character_id: int, body: CharacterUpdate, request: Request):
    return await request.app.state.services.characters.save(
        body.model_dump(exclude_none=True), character_id
    )


@router.delete("/characters/{character_id}")
async def delete_character(character_id: int, request: Request):
    status = await request.app.state.services.characters.delete(character_id)
    return {"status": status}


@router.post("/characters/{character_id}/images/{kind}")
async def upload_image(character_id: int, kind: Literal["cover", "background"], request: Request):
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_IMAGE_BYTES:
            raise SessionError("IMAGE_TOO_LARGE", "图片不能超过 10 MB。", 413)
        content.extend(chunk)
    return await request.app.state.services.characters.upload(character_id, kind, bytes(content))


@router.get("/media/{name}")
async def get_image(name: str, request: Request):
    if not re.fullmatch(r"[a-f0-9]{32}\.(jpg|png|webp)", name):
        raise SessionError("IMAGE_NOT_FOUND", "图片不存在。", 404)
    path = request.app.state.settings.data_directory / "images" / name
    if not path.is_file():
        raise SessionError("IMAGE_NOT_FOUND", "图片不存在。", 404)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/scene-assets/{name}")
async def get_character_asset(name: Literal["cafe.png", "studio.jpg", "night.jpg"]):
    return FileResponse(Path(__file__).resolve().parents[1] / "resources" / "images" / name)
