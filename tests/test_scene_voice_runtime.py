"""历史音色失配只暂停合成，不阻止文字交流。"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
import speechio
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_session_websocket import install_provider

from dialogue_lab.main import create_app


@pytest.mark.usefixtures("database")
def test_standalone_legacy_session_keeps_its_configured_voice(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test")
    monkeypatch.setenv("DIALOGUE_LAB_TTS_VOICE", "Emily_v3.1")
    application = create_app()
    with TestClient(application) as client:
        install_provider(application, monkeypatch)
        voices = []

        class Synthesizer:
            def __init__(self, config):
                pass

            def open_stream(self, *, options):
                voices.append(options.voice)
                raise RuntimeError("External speech boundary")

            def close(self):
                return SimpleNamespace(status="ok")

        monkeypatch.setattr(speechio, "Synthesizer", Synthesizer)
        sid = client.post("/api/sessions", json={"title": "Legacy"}).json()["session_id"]
        with client.websocket_connect(f"/api/sessions/{sid}/realtime") as socket:
            socket.receive_json()
            socket.send_json({"type": "submit", "text": "Hello", "request_id": str(uuid4())})
            seen = set()
            while not {"generation_finished", "audio_finished"}.issubset(seen):
                seen.add(socket.receive_json()["type"])
        assert voices == ["Emily_v3.1"]


@pytest.mark.asyncio
async def test_legacy_incompatible_voice_is_preserved_and_text_still_replies(database, monkeypatch):
    application = create_app()
    with TestClient(application) as client:
        install_provider(application, monkeypatch)
        scene = client.post(
            "/api/scenes",
            json={
                "name": "Legacy voice",
                "category": "Test",
                "character_name": "Emma",
                "system_prompt": "Be brief.",
                "tts_voice": "longanhuan_v3.1",
            },
        ).json()
        # 模拟升级前遗留的音色；正常编辑接口不会接受当前模型不支持的值。
        async with database.engine.begin() as connection:
            await connection.execute(
                text("UPDATE scenes SET tts_voice='retired-voice' WHERE scene_id=:id"),
                {"id": int(scene["scene_id"])},
            )
        current = client.get(f"/api/scenes/{scene['scene_id']}").json()
        assert current["tts_voice"] == "retired-voice"
        assert current["voice_available"] is False
        preview = client.post(
            "/api/settings/preview", json=client.get("/api/settings").json()
        ).json()
        assert any(row["scene_id"] == scene["scene_id"] for row in preview)
        speech_calls = []

        def unexpected_synthesis(config):
            speech_calls.append(config.model)
            raise RuntimeError("Should not synthesize incompatible voice")

        monkeypatch.setattr(speechio, "Synthesizer", unexpected_synthesis)
        sid = client.post(
            "/api/sessions", json={"title": "Test", "scene_id": scene["scene_id"]}
        ).json()["session_id"]
        with client.websocket_connect(f"/api/sessions/{sid}/realtime") as socket:
            socket.receive_json()
            socket.send_json({"type": "submit", "text": "Hello", "request_id": str(uuid4())})
            events = []
            while not {"generation_finished", "audio_finished"}.issubset(
                {e["type"] for e in events}
            ):
                events.append(socket.receive_json())
        assert any(e.get("code") == "VOICE_UNAVAILABLE" for e in events)
        assert any(e["type"] == "text_delta" for e in events)
        assert speech_calls == []
        assert len(client.get(f"/api/sessions/{sid}").json()["messages"]) == 2
