"""从公开 WebSocket 验证语音输入，不调用真实云端服务。"""

import pytest
import speechio
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from speechio_boundary import SpeechRuntime

from dialogue_lab.main import create_app


@pytest.fixture
def speech(monkeypatch):
    """只替换 speechio 包边界，避免测试访问真实模型和本地设备。"""
    runtime = SpeechRuntime()
    monkeypatch.setenv("DIALOGUE_LAB_STT_API_KEY", "test-credential")
    monkeypatch.setattr(speechio, "STTRuntime", lambda *args, **kwargs: runtime)
    return runtime


def test_missing_key_reports_configuration_error(monkeypatch) -> None:
    """没有凭据时返回可操作的错误，HTTP 服务仍可使用。"""
    monkeypatch.setenv("DIALOGUE_LAB_STT_API_KEY", "")
    with TestClient(create_app()) as client:
        with client.websocket_connect("/api/voice/input") as socket:
            event = socket.receive_json()
            assert event["type"] == "error"
            assert event["code"] == "STT_NOT_CONFIGURED"
        assert client.get("/api/health").status_code == 200


def test_stop_delivers_final_text_before_stopped(speech) -> None:
    """边识别边展示，结束输入后先交付尾句，再确认结束。"""
    with TestClient(create_app()) as client:
        with client.websocket_connect("/api/voice/input") as socket:
            assert socket.receive_json()["type"] == "ready"
            socket.send_bytes(b"\x00\x00" * 320)
            assert socket.receive_json() == {"type": "partial", "segment_id": 1, "text": "你好"}
            socket.send_json({"type": "stop"})
            assert socket.receive_json() == {
                "type": "final",
                "segment_id": 1,
                "text": "你好，世界。",
            }
            assert socket.receive_json() == {"type": "stopped"}
            assert speech.closed.is_set()
            assert speech.session.closed.is_set()


def test_disconnect_releases_recognition_resources(speech) -> None:
    """网页异常断线后不能继续持有模型和识别会话。"""
    with TestClient(create_app()) as client:
        with client.websocket_connect("/api/voice/input") as socket:
            assert socket.receive_json()["type"] == "ready"
            socket.send_bytes(b"\x00\x00" * 320)
            assert socket.receive_json()["type"] == "partial"
        assert speech.closed.wait(timeout=3)
        assert speech.session.closed.is_set()


def test_invalid_audio_is_rejected_and_resources_released(speech) -> None:
    """PCM16 不完整样本属于真实传输边界错误。"""
    with TestClient(create_app()) as client:
        with client.websocket_connect("/api/voice/input") as socket:
            assert socket.receive_json()["type"] == "ready"
            socket.send_bytes(b"\x00")
            event = socket.receive_json()
            assert event["type"] == "error"
            assert event["code"] == "INVALID_AUDIO"
            assert speech.closed.is_set()


def test_recognition_failure_reports_safe_error_and_closes(speech) -> None:
    """供应商异常内容不应进入网页，已启动资源仍需释放。"""
    from types import SimpleNamespace

    with TestClient(create_app()) as client:
        with client.websocket_connect("/api/voice/input") as socket:
            assert socket.receive_json()["type"] == "ready"
            failed = speech.session.event("failed")
            failed.error = SimpleNamespace(code="NETWORK_FAILED", message="private-response")
            speech.session.events.put(failed)
            event = socket.receive_json()
            assert event["type"] == "error"
            assert event["code"] == "STT_FAILED"
            assert "private-response" not in event["message"]
            assert speech.closed.is_set()


def test_real_speechio_can_start_and_end_silent_input(monkeypatch) -> None:
    """装配真实包和内置 VAD；只有静音，不产生云端识别请求。"""
    monkeypatch.setenv("DIALOGUE_LAB_STT_API_KEY", "test-credential")
    with TestClient(create_app()) as client:
        with client.websocket_connect("/api/voice/input") as socket:
            assert socket.receive_json()["type"] == "ready"
            socket.send_bytes(b"\x00\x00" * 3200)
            socket.send_json({"type": "stop"})
            assert socket.receive_json() == {"type": "stopped"}


def test_other_websites_cannot_open_local_voice_service(speech) -> None:
    """浏览器只能从同源页面连接，避免其他站点使用本地语音凭据。"""
    with TestClient(create_app()) as client:
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect(
                "/api/voice/input", headers={"origin": "https://unrelated.example"}
            ) as socket:
                socket.receive_json()
        assert rejected.value.code == 1008
