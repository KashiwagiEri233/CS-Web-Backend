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


def test_health_security_does_not_leak_auth_posture():
    """ER-48 / P1-1：/health/security 必须脱敏，不向匿名探针暴露安全配置姿态。

    不应返回 ``auth`` 块（AUTH_ENABLED、TOTP 密钥是否已配置等），
    仅保留组件健康/连通性状态（rate_limiter / token_blacklist / migration / multi_instance）。
    """
    response = TestClient(app).get("/health/security")
    assert response.status_code == 200

    body = response.json()
    # 脱敏核心断言：禁止泄露安全配置姿态
    assert "auth" not in body
    assert "enabled" not in body
    assert "totp_encryption_key_set" not in body

    # 保留的运维探针字段仍正常暴露
    for probe_key in ("status", "rate_limiter", "token_blacklist", "migration", "multi_instance"):
        assert probe_key in body
