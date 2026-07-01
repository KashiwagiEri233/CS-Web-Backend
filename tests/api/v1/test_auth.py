"""auth 路由端到端测试（不依赖数据库）。

覆盖 register 端点：验证走 AuthService.create_user 统一入口。
"""

import types

from fastapi import FastAPI
from starlette.testclient import TestClient

import app.api.v1.auth as auth_module
from app.api.v1.auth import router as auth_router
from app.core.exceptions import setup_exception_handlers
from app.database import get_db
from app.dependencies import get_current_superuser


def _fake_user(user_id=1, is_superuser=True):
    return types.SimpleNamespace(
        id=user_id, username="admin", email="a@t.com",
        full_name=None, is_active=True, is_superuser=is_superuser,
    )


class _FakeAuthService:
    """假 AuthService：记录 create_user 入参。"""

    def __init__(self, db):
        self.created = []

    async def create_user(self, user_data, is_superuser=False):
        self.created.append((user_data, is_superuser))
        return _fake_user(is_superuser=is_superuser)


def _client(monkeypatch):
    monkeypatch.setattr(auth_module, "AuthService", _FakeAuthService)
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(auth_router, prefix="/auth")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_superuser] = lambda: _fake_user()
    return TestClient(app, raise_server_exceptions=False)


def test_register_delegates_to_auth_service(monkeypatch):
    """更精确：通过 monkeypatch 捕获 service 实例，断言 create_user 被调用。"""
    captured = {}

    class _CapturingAuthService(_FakeAuthService):
        async def create_user(self, user_data, is_superuser=False):
            captured["called"] = True
            captured["is_superuser"] = is_superuser
            captured["username"] = user_data.username
            return _fake_user()

    monkeypatch.setattr(auth_module, "AuthService", _CapturingAuthService)
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(auth_router, prefix="/auth")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_superuser] = lambda: _fake_user()

    resp = TestClient(app, raise_server_exceptions=False).post(
        "/auth/register",
        json={"username": "bob", "email": "b@t.com", "password": "Str0ng!Pass"},
    )

    assert resp.status_code in (200, 201)
    assert captured.get("called") is True
    assert captured.get("is_superuser") is False
    assert captured.get("username") == "bob"


def test_register_weak_password_rejected(monkeypatch):
    """密码强度校验应在 schema 层生效（UserCreate 带验证）。"""
    monkeypatch.setattr(auth_module, "AuthService", _FakeAuthService)
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(auth_router, prefix="/auth")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_superuser] = lambda: _fake_user()

    resp = TestClient(app, raise_server_exceptions=False).post(
        "/auth/register",
        json={"username": "weak", "email": "w@t.com", "password": "123"},  # 弱密码
    )
    # 弱密码应被 422 拒绝，且响应可正常序列化（曾因 ctx 含 ValueError 崩溃）
    assert resp.status_code == 422
