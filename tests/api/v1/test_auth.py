"""auth 路由端到端测试（不依赖数据库）。

register 走 get_auth_service Depends；超管旁路 require_permission。
登录编排（防爆破/审计/激活检查）已下沉 AuthService.login，
其行为契约见 tests/services/test_auth_service.py 的 login 用例。
"""

import types

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.api.v1.auth import router as auth_router
from app.core.exceptions import (
    InvalidCredentialsException,
    UserNotActiveException,
    setup_exception_handlers,
)
from app.database import get_db
from app.dependencies import get_current_active_user
from app.dependencies_services import get_auth_service
from app.schemas.auth import TokenPair


def _fake_user(user_id=1, is_superuser=True):
    return types.SimpleNamespace(
        id=user_id,
        username="admin",
        email="a@t.com",
        full_name=None,
        is_active=True,
        is_superuser=is_superuser,
    )


def _token_pair() -> TokenPair:
    return TokenPair(
        access_token="a", refresh_token="r", token_type="bearer", expires_in=60
    )


class _FakeAuthService:
    def __init__(self, db=None):
        pass

    async def create_user_with_audit(self, user_data, *, actor, client_meta, via):
        return _fake_user()

    async def login(self, username, password, client_meta):
        return _token_pair()


def _build_app(auth_svc) -> tuple:
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(auth_router, prefix="/auth")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_active_user] = lambda: _fake_user()
    app.dependency_overrides[get_auth_service] = lambda: auth_svc
    return app


def test_register_delegates_to_create_user_with_audit():
    captured = {}

    class _Capturing(_FakeAuthService):
        async def create_user_with_audit(self, user_data, *, actor, client_meta, via):
            captured["called"] = True
            captured["username"] = user_data.username
            captured["actor"] = actor
            captured["via"] = via
            return _fake_user()

    client = TestClient(_build_app(_Capturing()), raise_server_exceptions=False)
    resp = client.post(
        "/auth/register",
        json={"username": "bob", "email": "b@t.com", "password": "Str0ng!Pass"},
    )

    assert resp.status_code in (200, 201)
    assert captured.get("called") is True
    assert captured.get("username") == "bob"
    assert captured.get("via") == "auth.register"
    assert captured.get("actor").username == "admin"


def test_register_weak_password_rejected():
    client = TestClient(_build_app(_FakeAuthService()), raise_server_exceptions=False)
    resp = client.post(
        "/auth/register",
        json={"username": "weak", "email": "w@t.com", "password": "123"},
    )
    assert resp.status_code == 422


def test_login_delegates_to_service():
    captured = {}

    class _Capturing(_FakeAuthService):
        async def login(self, username, password, client_meta):
            captured["username"] = username
            captured["client_meta"] = client_meta
            return _token_pair()

    client = TestClient(_build_app(_Capturing()), raise_server_exceptions=False)
    resp = client.post("/auth/login", data={"username": "admin", "password": "x"})

    assert resp.status_code == 200
    assert resp.json()["access_token"] == "a"
    assert captured["username"] == "admin"
    assert "ip_address" in captured["client_meta"]


def test_login_invalid_credentials_returns_401():
    class _Failing(_FakeAuthService):
        async def login(self, username, password, client_meta):
            raise InvalidCredentialsException()

    client = TestClient(_build_app(_Failing()), raise_server_exceptions=False)
    resp = client.post("/auth/login", data={"username": "ghost", "password": "bad"})
    assert resp.status_code == 401


def test_login_inactive_user_returns_401():
    class _Failing(_FakeAuthService):
        async def login(self, username, password, client_meta):
            raise UserNotActiveException(user_id=1)

    client = TestClient(_build_app(_Failing()), raise_server_exceptions=False)
    resp = client.post("/auth/login", data={"username": "admin", "password": "x"})
    assert resp.status_code == 401


def test_login_json_delegates_to_service():
    client = TestClient(_build_app(_FakeAuthService()), raise_server_exceptions=False)
    resp = client.post("/auth/login-json", json={"username": "admin", "password": "x"})
    assert resp.status_code == 200
    assert resp.json()["refresh_token"] == "r"
