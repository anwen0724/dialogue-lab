"""通过真实 HTTP 与隔离 PostgreSQL 验证用户角色。"""

import pytest
from conftest import TEST_DATABASE_URL
from fastapi.testclient import TestClient

from dialogue_lab.main import create_app


@pytest.mark.usefixtures("database")
def test_copy_builtin_character_and_failed_copy_leave_source_intact(monkeypatch, tmp_path):
    monkeypatch.setenv("DIALOGUE_LAB_DATA_DIRECTORY", str(tmp_path))
    with TestClient(create_app()) as client:
        source = client.get("/api/characters").json()[0]
        response = client.post(f"/api/characters/{source['character_id']}/copy")
        assert response.status_code == 201
        copied = response.json()
        for field in ("cover_image", "background_image"):
            assert copied[field] != source[field]
            assert client.get(copied[field]).content == client.get(source[field]).content

        # 在文件边界模拟背景丢失：不能留下半成品角色或本次已复制的封面。
        (tmp_path / "images" / copied["background_image"].rsplit("/", 1)[1]).unlink()
        existing_files = set(tmp_path.rglob("*"))
        existing_characters = client.get("/api/characters").json()
        failed = client.post(f"/api/characters/{copied['character_id']}/copy")
        assert failed.status_code >= 400
        assert client.get("/api/characters").json() == existing_characters
        assert set(tmp_path.rglob("*")) == existing_files
        assert client.get(source["background_image"]).status_code == 200


@pytest.mark.usefixtures("database")
def test_copy_character_keeps_independent_files_and_does_not_copy_sessions(monkeypatch, tmp_path):
    from base64 import b64decode

    monkeypatch.setenv("DIALOGUE_LAB_DATA_DIRECTORY", str(tmp_path))
    png = b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII="
    )
    with TestClient(create_app()) as client:
        source = client.post(
            "/api/characters",
            json={
                "name": "Emma · 英语交流",
                "category": "英语",
                "character_name": "Emma",
                "tts_voice": "Emily_v3.1",
                "system_prompt": "You are {{character_name}}.",
            },
        ).json()
        source_id = source["character_id"]
        for kind in ("cover", "background"):
            source = client.post(f"/api/characters/{source_id}/images/{kind}", content=png).json()
        session = client.post(
            "/api/sessions",
            json={
                "title": "原会话",
                "character_id": source_id,
            },
        ).json()
        response = client.post(f"/api/characters/{source_id}/copy")
        assert response.status_code == 201
        copied = response.json()
        copied_id = copied["character_id"]
        assert copied_id != source_id
        assert copied["name"] == "Emma · 英语交流（副本）"
        for field in ("category", "character_name", "system_prompt", "tts_voice"):
            assert copied[field] == source[field]
        assert client.get("/api/sessions", params={"character_id": copied_id}).json() == []
        assert (
            client.get(f"/api/sessions/{session['session_id']}").json()["character_id"] == source_id
        )
        for field in ("cover_image", "background_image"):
            assert copied[field] != source[field]
            assert client.get(copied[field]).content == png
        client.patch(f"/api/characters/{copied_id}", json={"system_prompt": "New instruction."})
        assert (
            client.get(f"/api/characters/{source_id}").json()["system_prompt"]
            == source["system_prompt"]
        )
        assert client.delete(f"/api/characters/{copied_id}").json()["status"] == "deleted"
        for field in ("cover_image", "background_image"):
            assert client.get(source[field]).content == png


@pytest.mark.usefixtures("database")
def test_character_voice_is_validated_and_saved_independently(monkeypatch, tmp_path):
    monkeypatch.setenv("DIALOGUE_LAB_DATA_DIRECTORY", str(tmp_path))
    with TestClient(create_app()) as client:
        characters = client.get("/api/characters").json()
        first, second = characters[:2]
        assert "tts_voice" in first
        endpoint = f"/api/characters/{first['character_id']}"
        assert client.patch(endpoint, json={"tts_voice": "Emily_v3.1"}).status_code == 200
        assert client.get(endpoint).json()["tts_voice"] == "Emily_v3.1"
        assert (
            client.get(f"/api/characters/{second['character_id']}").json()["tts_voice"]
            == second["tts_voice"]
        )
        assert client.patch(endpoint, json={"tts_voice": "unknown"}).status_code == 422
        assert client.get(endpoint).json()["tts_voice"] == "Emily_v3.1"


@pytest.mark.usefixtures("database")
def test_user_can_create_edit_and_reopen_character(monkeypatch, tmp_path):
    monkeypatch.setenv("DIALOGUE_LAB_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("DIALOGUE_LAB_DATA_DIRECTORY", str(tmp_path))
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/characters",
            json={
                "name": "我的咖啡馆",
                "category": "英语",
                "character_name": "Emma",
                "tts_voice": "longanhuan_v3.1",
                "system_prompt": "你是 Emma，使用英语自然交流。",
            },
        )
        assert response.status_code == 201
        character = response.json()
        character_id = character["character_id"]
        assert character["system_prompt"] == "你是 Emma，使用英语自然交流。"
        edited = client.patch(
            f"/api/characters/{character_id}",
            json={
                "name": "下班后",
                "system_prompt": "你是 Emma，谈论日常生活。",
            },
        )
        assert edited.status_code == 200
    with TestClient(create_app()) as client:
        reopened = client.get(f"/api/characters/{character_id}").json()
        assert reopened["name"] == "下班后"
        assert reopened["system_prompt"] == "你是 Emma，谈论日常生活。"
        assert any(s["character_id"] == character_id for s in client.get("/api/characters").json())


@pytest.mark.usefixtures("database")
def test_character_sessions_are_filtered_and_character_with_history_is_archived(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DIALOGUE_LAB_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("DIALOGUE_LAB_DATA_DIRECTORY", str(tmp_path))
    with TestClient(create_app()) as client:
        character = client.post(
            "/api/characters",
            json={
                "name": "Practice",
                "category": "English",
                "character_name": "Emma",
                "tts_voice": "longanhuan_v3.1",
                "system_prompt": "Be brief.",
            },
        ).json()
        character_id = character["character_id"]
        session = client.post(
            "/api/sessions", json={"title": "新会话", "character_id": character_id}
        )
        assert session.status_code == 201
        sid = session.json()["session_id"]
        client.post("/api/sessions", json={"title": "旧会话"})
        listed = client.get("/api/sessions", params={"character_id": character_id}).json()
        assert [s["session_id"] for s in listed] == [sid]
        assert listed[0]["message_count"] == 0
        assert client.delete(f"/api/characters/{character_id}").json()["status"] == "archived"
        assert all(s["character_id"] != character_id for s in client.get("/api/characters").json())
        assert client.get(f"/api/sessions/{sid}").json()["character_id"] == character_id
        assert client.get(f"/api/characters/{character_id}").json()["system_prompt"] == "Be brief."
        assert (
            client.post(
                "/api/sessions", json={"title": "不能创建", "character_id": character_id}
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
        character = client.post(
            "/api/characters",
            json={
                "name": "Test",
                "category": "Test",
                "character_name": "Test",
                "tts_voice": "longanhuan_v3.1",
                "system_prompt": "Be brief.",
            },
        ).json()
        endpoint = f"/api/characters/{character['character_id']}/images/background"
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
            client.get(f"/api/characters/{character['character_id']}").json()["background_image"]
            == reference
        )
        assert (
            client.delete(f"/api/characters/{character['character_id']}").json()["status"]
            == "deleted"
        )
        assert client.get(f"/api/characters/{character['character_id']}").status_code == 404
