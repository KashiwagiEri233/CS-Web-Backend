"""auth 路由端到端测试（不依赖数据库）。

register 走 get_auth_service + get_verification_service Depends；
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
    ValidationException,
    setup_exception_handlers,
)
from app.database import get_db
from app.dependencies import get_current_active_user
from app.dependencies_services import get_auth_service, get_verification_service
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


def _login_response() -> dict:
    pair = _token_pair()
    return {
        "requires_2fa": False,
        "two_factor_token": None,
        "access_token": pair.access_token,
        "refresh_token": pair.refresh_token,
        "token_type": pair.token_type,
        "expires_in": pair.expires_in,
    }


class _FakeAuthService:
    def __init__(self, db=None):
        pass

    async def register(self, email, password, client_meta):
        return _token_pair()

    async def login(self, username, password, client_meta):
        return _token_pair()

    async def login_by_email(self, email, password, client_meta):
        return {"requires_2fa": False, "two_factor_token": None, "pair": _token_pair()}


class _FakeVerificationService:
    def __init__(self, db=None):
        pass

    async def verify_or_raise(self, email, code):
        return None


def _build_app(auth_svc, verification_svc=None) -> tuple:
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(auth_router, prefix="/auth")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_active_user] = lambda: _fake_user()
    app.dependency_overrides[get_auth_service] = lambda: auth_svc
    app.dependency_overrides[get_verification_service] = lambda: (
        verification_svc or _FakeVerificationService()
    )
    return app


def test_register_delegates_to_service():
    captured = {}

    class _Capturing(_FakeAuthService):
        async def register(self, email, password, client_meta):
            captured["email"] = email
            captured["password"] = password
            captured["client_meta"] = client_meta
            return _token_pair()

    client = TestClient(_build_app(_Capturing()), raise_server_exceptions=False)
    resp = client.post(
        "/auth/register",
        json={"email": "b@t.com", "password": "Str0ng!Pass", "code": "123456"},
    )

    assert resp.status_code == 200
    assert resp.json()["access_token"] == "a"
    assert captured.get("email") == "b@t.com"
    assert captured.get("password") == "Str0ng!Pass"
    assert "ip_address" in captured.get("client_meta", {})


def test_register_invalid_code_rejected():
    class _Rejecting(_FakeVerificationService):
        async def verify_or_raise(self, email, code):
            raise ValidationException(
                message="验证码错误或已过期", error_code="VERIFICATION_CODE_INVALID"
            )

    client = TestClient(
        _build_app(_FakeAuthService(), _Rejecting()), raise_server_exceptions=False
    )
    resp = client.post(
        "/auth/register",
        json={"email": "b@t.com", "password": "Str0ng!Pass", "code": "000000"},
    )
    assert resp.status_code == 422


def test_register_weak_password_rejected():
    client = TestClient(_build_app(_FakeAuthService()), raise_server_exceptions=False)
    resp = client.post(
        "/auth/register",
        json={"email": "w@t.com", "password": "123", "code": "123456"},
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


def test_login_email_delegates_to_service():
    captured = {}

    class _Capturing(_FakeAuthService):
        async def login_by_email(self, email, password, client_meta):
            captured["email"] = email
            return {
                "requires_2fa": False,
                "two_factor_token": None,
                "pair": _token_pair(),
            }

    client = TestClient(_build_app(_Capturing()), raise_server_exceptions=False)
    resp = client.post(
        "/auth/login-email", json={"email": "b@t.com", "password": "Str0ng!Pass"}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "a"
    assert captured["email"] == "b@t.com"


def test_login_email_requires_2fa_shape():
    class _TwoFA(_FakeAuthService):
        async def login_by_email(self, email, password, client_meta):
            return {"requires_2fa": True, "two_factor_token": "tok", "pair": None}

    client = TestClient(_build_app(_TwoFA()), raise_server_exceptions=False)
    resp = client.post(
        "/auth/login-email", json={"email": "b@t.com", "password": "Str0ng!Pass"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_2fa"] is True
    assert body["two_factor_token"] == "tok"
    assert body["access_token"] is None
