"""应用设置和可选目录接口；不会返回凭据。"""

from typing import Annotated

from fastapi import APIRouter, Query, Request

from dialogue_lab.sessions.types import SessionError
from dialogue_lab.settings.types import ApplicationSettings, ModelSelection
from dialogue_lab.voice.catalog import get_speech_model

router = APIRouter()


@router.get("/settings")
async def get_settings(request: Request):
    return request.app.state.services.application_settings.current


@router.patch("/settings")
async def save_settings(body: ApplicationSettings, request: Request):
    try:
        return await request.app.state.services.application_settings.update(body)
    except OSError:
        raise SessionError(
            "SETTINGS_WRITE_FAILED", "设置文件保存失败，原设置仍然有效。", 500
        ) from None


@router.post("/settings/preview")
async def preview_settings(body: ApplicationSettings, request: Request):
    """只读检查目标 TTS 的音色兼容性，覆盖仍可打开的归档角色。"""
    services = request.app.state.services
    services.application_settings.validate(body)
    voices = dict(get_speech_model("tts", body.tts).voices)
    return [
        {
            "character_id": str(row["character_id"]),
            "name": row["name"],
            "tts_voice": row["tts_voice"],
        }
        for row in await services.characters.store.list(include_archived=True)
        if row["tts_voice"] not in voices
    ]


@router.get("/models")
async def list_models(request: Request):
    return await request.app.state.services.application_settings.dialogue_models()


@router.get("/speech-models")
async def list_speech_models(request: Request):
    return request.app.state.services.application_settings.speech_models()


@router.get("/voices")
async def list_voices(
    provider_id: Annotated[str, Query(pattern=r"\S")],
    model_id: Annotated[str, Query(pattern=r"\S")],
):
    model = get_speech_model("tts", ModelSelection(provider_id=provider_id, model_id=model_id))
    return [{"id": voice_id, "name": name} for voice_id, name in model.voices]
