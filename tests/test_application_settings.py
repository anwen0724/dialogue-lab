"""从 HTTP 入口验证设置保存与目录，不调用真实模型。"""

import pytest
from fastapi.testclient import TestClient

from dialogue_lab.main import create_app


def test_voice_catalog_rejects_blank_model_selection():
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.get("/api/voices", params={"provider_id": "bailian", "model_id": " "})
        assert response.status_code == 422


def test_failed_file_replace_keeps_previous_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("DIALOGUE_LAB_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test")
    with TestClient(create_app()) as client:
        before = client.get("/api/settings").json()
        proposal = {**before, "dialogue": {**before["dialogue"], "model_id": "deepseek-v4-pro"}}
        original_file = (tmp_path / "settings.json").read_bytes()

        def fail_replace(*args):
            raise OSError("Disk failure")

        # 仅在磁盘替换边界注入故障；保留真实校验、序列化与 HTTP 处理。
        with monkeypatch.context() as patch:
            patch.setattr("os.replace", fail_replace)
            assert client.patch("/api/settings", json=proposal).status_code == 500
        assert client.get("/api/settings").json() == before
        assert (tmp_path / "settings.json").read_bytes() == original_file


@pytest.mark.usefixtures("database")
def test_tts_preview_reports_scenes_without_rewriting_their_voice(monkeypatch, tmp_path):
    monkeypatch.setenv("DIALOGUE_LAB_DATA_DIRECTORY", str(tmp_path))
    with TestClient(create_app()) as client:
        settings = client.get("/api/settings").json()
        before = client.get("/api/scenes").json()
        result = client.post("/api/settings/preview", json=settings)
        assert result.status_code == 200
        assert result.json() == [
            {"scene_id": scene["scene_id"], "name": scene["name"], "tts_voice": scene["tts_voice"]}
            for scene in before
            if not scene["voice_available"]
        ]
        assert client.get("/api/scenes").json() == before


def test_model_selection_survives_restart_and_overrides_initial_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DIALOGUE_LAB_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-bailian")
    with TestClient(create_app()) as client:
        response = client.get("/api/settings")
        assert response.status_code == 200
        settings = response.json()
        settings["dialogue"] = {
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "reasoning": "high",
        }
        assert client.patch("/api/settings", json=settings).status_code == 200
    monkeypatch.setenv("DIALOGUE_LAB_AI_MODEL", "deepseek-flash")
    with TestClient(create_app()) as client:
        assert client.get("/api/settings").json() == settings
    assert "test-deepseek" not in (tmp_path / "settings.json").read_text()


@pytest.mark.parametrize(
    "selection",
    [
        {"provider_id": "deepseek", "model_id": "missing", "reasoning": None},
        {"provider_id": "deepseek", "model_id": "deepseek-flash", "reasoning": "made-up"},
        {"provider_id": "openai", "model_id": "gpt-6.1-sol", "reasoning": None},
    ],
)
def test_invalid_or_unconfigured_model_does_not_replace_saved_settings(
    monkeypatch, tmp_path, selection
):
    monkeypatch.setenv("DIALOGUE_LAB_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test")
    with TestClient(create_app()) as client:
        before = client.get("/api/settings").json()
        proposed = {**before, "dialogue": selection}
        assert client.patch("/api/settings", json=proposed).status_code == 422
        assert client.get("/api/settings").json() == before
        models = client.get("/api/models").json()
        assert all(not model["available"] for model in models if model["provider_id"] == "openai")
