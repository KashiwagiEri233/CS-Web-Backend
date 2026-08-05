"""应用工厂路由实例测试。"""

from app.main import app, create_app
from starlette.testclient import TestClient


def test_create_app_returns_distinct_instances_with_core_routes():
    first = create_app()
    second = create_app()

    assert first is not second
    assert app is not first

    response = TestClient(first).get("/health")
    assert response.status_code == 200
    assert response.headers["x-request-id"]
