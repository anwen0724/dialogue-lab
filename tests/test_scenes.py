"""通过真实 HTTP 与隔离 PostgreSQL 验证用户场景。"""

import pytest
from conftest import TEST_DATABASE_URL
from fastapi.testclient import TestClient

from dialogue_lab.main import create_app


@pytest.mark.usefixtures("database")
def test_user_can_create_edit_and_reopen_scene(monkeypatch, tmp_path):
    monkeypatch.setenv("DIALOGUE_LAB_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("DIALOGUE_LAB_DATA_DIRECTORY", str(tmp_path))
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/scenes",
            json={
                "name": "我的咖啡馆",
                "category": "英语",
                "character_name": "Emma",
                "system_prompt": "你是 Emma，使用英语自然交流。",
            },
        )
        assert response.status_code == 201
        scene = response.json()
        scene_id = scene["scene_id"]
        assert scene["system_prompt"] == "你是 Emma，使用英语自然交流。"
        edited = client.patch(
            f"/api/scenes/{scene_id}",
            json={
                "name": "下班后",
                "system_prompt": "你是 Emma，谈论日常生活。",
            },
        )
        assert edited.status_code == 200
    with TestClient(create_app()) as client:
        reopened = client.get(f"/api/scenes/{scene_id}").json()
        assert reopened["name"] == "下班后"
        assert reopened["system_prompt"] == "你是 Emma，谈论日常生活。"
        assert any(s["scene_id"] == scene_id for s in client.get("/api/scenes").json())


@pytest.mark.usefixtures("database")
def test_scene_sessions_are_filtered_and_scene_with_history_is_archived(monkeypatch, tmp_path):
    monkeypatch.setenv("DIALOGUE_LAB_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("DIALOGUE_LAB_DATA_DIRECTORY", str(tmp_path))
    with TestClient(create_app()) as client:
        scene = client.post(
            "/api/scenes",
            json={
                "name": "Practice",
                "category": "English",
                "character_name": "Emma",
                "system_prompt": "Be brief.",
            },
        ).json()
        scene_id = scene["scene_id"]
        session = client.post("/api/sessions", json={"title": "新会话", "scene_id": scene_id})
        assert session.status_code == 201
        sid = session.json()["session_id"]
        client.post("/api/sessions", json={"title": "旧会话"})
        listed = client.get("/api/sessions", params={"scene_id": scene_id}).json()
        assert [s["session_id"] for s in listed] == [sid]
        assert listed[0]["message_count"] == 0
        assert client.delete(f"/api/scenes/{scene_id}").json()["status"] == "archived"
        assert all(s["scene_id"] != scene_id for s in client.get("/api/scenes").json())
        assert client.get(f"/api/sessions/{sid}").json()["scene_id"] == scene_id
        assert client.get(f"/api/scenes/{scene_id}").json()["system_prompt"] == "Be brief."
        assert (
            client.post(
                "/api/sessions", json={"title": "不能创建", "scene_id": scene_id}
            ).status_code
            == 409
        )


@pytest.mark.usefixtures("database")
def test_uploaded_background_is_saved_and_invalid_image_preserves_it(monkeypatch, tmp_path):
    from base64 import b64decode

    monkeypatch.setenv("DIALOGUE_LAB_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("DIALOGUE_LAB_DATA_DIRECTORY", str(tmp_path))
    png = b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII="
    )
    with TestClient(create_app()) as client:
        scene = client.post(
            "/api/scenes",
            json={
                "name": "Test",
                "category": "Test",
                "character_name": "Test",
                "system_prompt": "Be brief.",
            },
        ).json()
        endpoint = f"/api/scenes/{scene['scene_id']}/images/background"
        uploaded = client.post(endpoint, content=png, headers={"content-type": "image/png"})
        assert uploaded.status_code == 200
        reference = uploaded.json()["background_image"]
        assert client.get(reference).content == png
        assert (
            client.post(
                endpoint, content=b"not an image", headers={"content-type": "image/png"}
            ).status_code
            == 422
        )
        assert (
            client.get(f"/api/scenes/{scene['scene_id']}").json()["background_image"] == reference
        )
        assert client.delete(f"/api/scenes/{scene['scene_id']}").json()["status"] == "deleted"
        assert client.get(f"/api/scenes/{scene['scene_id']}").status_code == 404
