"""从会话 WebSocket 验证接入、持久化及控制权。"""

import asyncio
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
import speechio
from ai import create_provider
from ai.auth.api_key import ApiKeyAuth
from conftest import TEST_DATABASE_URL
from fastapi.testclient import TestClient
from model_provider import ScriptedAdapter
from speechio_boundary import SpeechRuntime

from dialogue_lab.main import create_app

pytestmark = pytest.mark.usefixtures("database")


def test_existing_connection_uses_saved_model_and_voice_on_next_reply(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "speech-test")
    application = create_app()
    with TestClient(application) as client:
        models = application.state.services.models
        available = models.get_models("deepseek")
        release = Event()
        started = Event()

        class PausedAdapter(ScriptedAdapter):
            async def stream_simple(self, model, context, auth, options):
                async for event in super().stream_simple(model, context, auth, options):
                    if len(self.inputs) == 1 and event.type == "text_delta":
                        started.set()
                        if not await asyncio.to_thread(release.wait, 5):
                            raise RuntimeError("Test did not release first reply")
                    yield event

        adapter = PausedAdapter([["First"], ["Second"]])
        models.set_provider(
            create_provider(
                "deepseek",
                models=available,
                auth=ApiKeyAuth(keyless=True),
                adapters={available[0].api: adapter},
            ),
            owns_provider=True,
        )
        synthesis_requests = []
        voices = []

        class Synthesizer:
            def __init__(self, config):
                synthesis_requests.append(config)

            def open_stream(self, *, options):
                voices.append(options.voice)
                raise RuntimeError("External speech boundary")

            def close(self):
                return SimpleNamespace(status="ok")

        monkeypatch.setattr(speechio, "Synthesizer", Synthesizer)
        character_id = client.get("/api/characters").json()[0]["character_id"]
        client.patch(f"/api/characters/{character_id}", json={"tts_voice": "longanhuan_v3.1"})
        sid = client.post(
            "/api/sessions", json={"title": "Switch", "character_id": character_id}
        ).json()["session_id"]
        with client.websocket_connect(f"/api/sessions/{sid}/realtime") as socket:
            socket.receive_json()
            for index in range(2):
                socket.send_json(
                    {"type": "submit", "request_id": str(uuid4()), "text": f"Turn {index}"}
                )
                if index == 0:
                    try:
                        assert started.wait(3)
                        settings = client.get("/api/settings").json()
                        settings["dialogue"]["model_id"] = "deepseek-v4-pro"
                        settings["dialogue"]["reasoning"] = "high"
                        assert client.patch("/api/settings", json=settings).status_code == 200
                        assert (
                            client.patch(
                                f"/api/characters/{character_id}", json={"tts_voice": "Emily_v3.1"}
                            ).status_code
                            == 200
                        )
                    finally:
                        release.set()
                seen = set()
                while not {"generation_finished", "audio_finished"}.issubset(seen):
                    seen.add(socket.receive_json()["type"])
        assert [call[0].id for call in adapter.calls] == ["deepseek-flash", "deepseek-v4-pro"]
        assert adapter.calls[1][2].reasoning == "high"
        assert synthesis_requests[1].api_key == "speech-test"
        assert voices == ["longanhuan_v3.1", "Emily_v3.1"]


def install_provider(application, monkeypatch, replies=None):
    models = application.state.services.models
    model = models.get_model("deepseek", "deepseek-flash")
    adapter = ScriptedAdapter(replies or [["Hello back"]])
    models.set_provider(
        create_provider(
            "deepseek", models=[model], auth=ApiKeyAuth(keyless=True), adapters={model.api: adapter}
        ),
        owns_provider=True,
    )

    def unavailable(config):
        raise RuntimeError("TTS unavailable in this integration")

    monkeypatch.setattr(speechio, "Synthesizer", unavailable)
    return adapter


def test_only_first_connection_controls_session(monkeypatch):
    monkeypatch.setenv(
        "DIALOGUE_LAB_DATABASE_URL",
        TEST_DATABASE_URL,
    )
    with TestClient(create_app()) as client:
        presets = client.get("/api/presets")
        assert presets.status_code == 200
        assert "general" in presets.json()
        session_id = client.post("/api/sessions", json={"title": "Test"}).json()["session_id"]
        with client.websocket_connect(f"/api/sessions/{session_id}/realtime") as first:
            assert first.receive_json()["can_control"] is True
            with client.websocket_connect(f"/api/sessions/{session_id}/realtime") as second:
                assert second.receive_json()["can_control"] is False
                second.send_json(
                    {
                        "type": "submit",
                        "request_id": str(uuid4()),
                        "text": "Hello",
                        "preset": "general",
                    }
                )
                assert second.receive_json()["code"] == "SESSION_CONTROL_CONFLICT"


def test_text_submission_is_saved_and_streams_reply(monkeypatch):
    monkeypatch.setenv(
        "DIALOGUE_LAB_DATABASE_URL",
        TEST_DATABASE_URL,
    )
    application = create_app()
    with TestClient(application) as client:
        install_provider(application, monkeypatch)
        session_id = client.post("/api/sessions", json={"title": "Test"}).json()["session_id"]
        with client.websocket_connect(f"/api/sessions/{session_id}/realtime") as socket:
            connected = socket.receive_json()
            assert connected["type"] == "connected"
            assert connected["messages"] == []
            socket.send_json(
                {"type": "submit", "request_id": str(uuid4()), "text": "Hello", "preset": "general"}
            )
            assert socket.receive_json()["type"] == "message_saved"
            events = []
            while True:
                event = socket.receive_json()
                events.append(event)
                if event["type"] == "generation_finished":
                    break
            assert any(event["type"] == "text_delta" for event in events)
        saved = client.get(f"/api/sessions/{session_id}").json()["messages"]
        assert len(saved) == 2
        assert saved[1]["message_json"]["content"][0]["text"] == "Hello back"


def test_recording_tail_is_submitted_once_before_recording_stops(monkeypatch):
    monkeypatch.setenv(
        "DIALOGUE_LAB_DATABASE_URL",
        TEST_DATABASE_URL,
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test")
    speech = SpeechRuntime()
    credentials_match = []

    def create_recognition(config, **kwargs):
        credentials_match.append(config.api_key == "test")
        return speech

    monkeypatch.setattr(speechio, "STTRuntime", create_recognition)
    application = create_app()
    with TestClient(application) as client:
        adapter = install_provider(application, monkeypatch)
        session_id = client.post("/api/sessions", json={"title": "Test"}).json()["session_id"]
        with client.websocket_connect(f"/api/sessions/{session_id}/realtime") as socket:
            connected = socket.receive_json()
            assert connected["type"] == "connected"
            assert connected["messages"] == []
            socket.send_json({"type": "start_recording", "preset": "general"})
            assert socket.receive_json()["type"] == "recording_ready"
            socket.send_bytes(b"\x00\x00" * 320)
            assert socket.receive_json()["type"] == "partial"
            socket.send_json({"type": "stop_recording"})
            events = []
            while not {"recording_stopped", "generation_finished"}.issubset(
                {event["type"] for event in events}
            ):
                events.append(socket.receive_json())
            assert len([e for e in events if e["type"] == "final"]) == 1
        saved = client.get(f"/api/sessions/{session_id}").json()["messages"]
        assert len(saved) == 2
        assert saved[0]["message_json"]["source"] == "voice"
        assert len(adapter.inputs) == 1
        assert speech.closed.is_set()
    assert credentials_match == [True]


def test_character_identity_update_applies_to_next_turn_and_title_uses_real_input(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DIALOGUE_LAB_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("DIALOGUE_LAB_DATA_DIRECTORY", str(tmp_path))
    application = create_app()
    with TestClient(application) as client:
        adapter = install_provider(
            application, monkeypatch, [["Hi, I'm Emma."], ["Nice to meet you."]]
        )
        character = client.post(
            "/api/characters",
            json={
                "name": "Cafe",
                "category": "English",
                "character_name": "Emma",
                "tts_voice": "longanhuan_v3.1",
                "system_prompt": "You are Emma, a coffee lover.",
            },
        ).json()
        sid = client.post(
            "/api/sessions", json={"title": "新会话", "character_id": character["character_id"]}
        ).json()["session_id"]
        with client.websocket_connect(f"/api/sessions/{sid}/realtime") as socket:
            socket.receive_json()
            socket.send_json({"type": "start_session", "request_id": str(uuid4())})
            while socket.receive_json()["type"] != "generation_finished":
                pass
            assert adapter.inputs[0].messages[0].content == "You are Emma, a coffee lover."
            client.patch(
                f"/api/characters/{character['character_id']}",
                json={"system_prompt": "You are Emma, a tea lover."},
            )
            socket.send_json({"type": "submit", "request_id": str(uuid4()), "text": "I like tea."})
            while socket.receive_json()["type"] != "generation_finished":
                pass
            assert adapter.inputs[1].messages[0].content == "You are Emma, a tea lover."
        listed = client.get(
            "/api/sessions", params={"character_id": character["character_id"]}
        ).json()[0]
        assert listed["title"] == "I like tea."
        assert listed["message_count"] == 3
        assert listed["latest_message"] == "Nice to meet you."


def test_character_rename_updates_model_prompt_without_rewriting_document(monkeypatch, tmp_path):
    monkeypatch.setenv("DIALOGUE_LAB_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("DIALOGUE_LAB_DATA_DIRECTORY", str(tmp_path))
    application = create_app()
    template = "You are {{character_name}}, an English partner."
    with TestClient(application) as client:
        adapter = install_provider(application, monkeypatch, [["Hello"], ["Hi again"]])
        character = client.post(
            "/api/characters",
            json={
                "name": "Cafe",
                "category": "English",
                "character_name": "Emma",
                "tts_voice": "longanhuan_v3.1",
                "system_prompt": template,
            },
        ).json()
        character_url = f"/api/characters/{character['character_id']}"
        sid = client.post(
            "/api/sessions", json={"title": "新会话", "character_id": character["character_id"]}
        ).json()["session_id"]
        with client.websocket_connect(f"/api/sessions/{sid}/realtime") as socket:
            socket.receive_json()
            socket.send_json({"type": "start_session", "request_id": str(uuid4())})
            while socket.receive_json()["type"] != "generation_finished":
                pass
            assert adapter.inputs[0].messages[0].content == "You are Emma, an English partner."
            changed = client.patch(character_url, json={"character_name": "Alice"}).json()
            assert changed["character_name"] == "Alice"
            assert changed["system_prompt"] == template
            socket.send_json({"type": "submit", "request_id": str(uuid4()), "text": "Hello"})
            while socket.receive_json()["type"] != "generation_finished":
                pass
            assert adapter.inputs[1].messages[0].content == "You are Alice, an English partner."
        assert client.get(character_url).json()["system_prompt"] == template
