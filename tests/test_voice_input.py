"""会话连接中的语音边界、失败和资源清理；替身只替换 speechio。"""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
import speechio
from conftest import TEST_DATABASE_URL
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from pydantic import SecretStr
from speechio_boundary import SpeechRuntime

from dialogue_lab.main import create_app

pytestmark = pytest.mark.usefixtures("database")


@pytest.fixture
def speech(monkeypatch):
    runtime = SpeechRuntime()
    monkeypatch.setenv("DIALOGUE_LAB_STT_API_KEY", "test-credential")
    monkeypatch.setattr(speechio, "STTRuntime", lambda *args, **kwargs: runtime)
    return runtime


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv(
        "DIALOGUE_LAB_DATABASE_URL",
        TEST_DATABASE_URL,
    )
    with TestClient(create_app()) as client:
        yield client


@contextmanager
def recording(client):
    session_id = client.post("/api/sessions", json={"title": "Voice test"}).json()["session_id"]
    with client.websocket_connect(f"/api/sessions/{session_id}/realtime") as socket:
        assert socket.receive_json()["type"] == "connected"
        socket.send_json({"type": "start_recording", "preset": "general"})
        yield socket


def test_missing_key_reports_configuration_error(monkeypatch, client):
    client.app.state.services.settings.stt_api_key = SecretStr("")
    with recording(client) as socket:
        assert socket.receive_json()["code"] == "STT_NOT_CONFIGURED"
        assert socket.receive_json()["type"] == "recording_stopped"
    assert client.get("/api/health").status_code == 200


def test_disconnect_releases_recognition_resources(speech, client):
    with recording(client) as socket:
        assert socket.receive_json()["type"] == "recording_ready"
        socket.send_bytes(b"\0\0" * 320)
        assert socket.receive_json()["type"] == "partial"
    assert speech.closed.wait(timeout=3)
    assert speech.session.closed.is_set()


def test_invalid_audio_stops_recording_and_releases_resources(speech, client):
    with recording(client) as socket:
        assert socket.receive_json()["type"] == "recording_ready"
        socket.send_bytes(b"\0")
        assert socket.receive_json()["code"] == "INVALID_AUDIO"
        assert speech.closed.wait(timeout=2)
        assert socket.receive_json()["type"] == "recording_stopped"


def test_recognition_failure_reports_safe_error_and_closes(speech, client):
    with recording(client) as socket:
        assert socket.receive_json()["type"] == "recording_ready"
        failed = speech.session.event("failed")
        failed.error = SimpleNamespace(code="NETWORK_FAILED", message="private-response")
        speech.session.events.put(failed)
        event = socket.receive_json()
        assert event["code"] == "STT_FAILED"
        assert "private-response" not in event["message"]
        assert socket.receive_json()["type"] == "recording_stopped"
        assert speech.closed.is_set()


def test_real_speechio_can_start_and_end_silent_input(monkeypatch, client):
    client.app.state.services.settings.stt_api_key = SecretStr("test-credential")
    with recording(client) as socket:
        assert socket.receive_json()["type"] == "recording_ready"
        socket.send_bytes(b"\0\0" * 3200)
        socket.send_json({"type": "stop_recording"})
        assert socket.receive_json()["type"] == "recording_stopped"


def test_other_websites_cannot_open_local_voice_service(client):
    session_id = client.post("/api/sessions", json={"title": "Voice test"}).json()["session_id"]
    with pytest.raises(WebSocketDisconnect) as rejected:
        with client.websocket_connect(
            f"/api/sessions/{session_id}/realtime", headers={"origin": "https://unrelated.example"}
        ) as socket:
            socket.receive_json()
    assert rejected.value.code == 1008
