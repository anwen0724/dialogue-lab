"""通过公开 HTTP 接口验证服务存活契约。"""

from fastapi.testclient import TestClient

from dialogue_lab.main import create_app


def test_health_reports_service_alive() -> None:
    """应用启动后，健康接口应返回成功状态和约定的 JSON。"""
    with TestClient(create_app()) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
