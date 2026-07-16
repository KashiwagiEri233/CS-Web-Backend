"""auth 路由端到端测试（不依赖数据库）。

register 走 get_auth_service Depends；超管旁路 require_permission。
"""

import types

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.api.v1.auth import router as auth_router
from app.core.exceptions import setup_exception_handlers
from app.database import get_db
from app.dependencies import get_current_active_user
from app.dependencies_services import get_audit_service, get_auth_service
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


class _FakeAuthService:
    def __init__(self, db=None):
        self.created = []

    async def create_user(self, user_data, is_superuser=False, commit=True):
        self.created.append((user_data, is_superuser))
        return _fake_user(is_superuser=is_superuser)


class _FakeAuditService:
    def __init__(self, db=None):
        pass

    async def record(self, **kwargs):
        return None

    async def record_atomic(self, **kwargs):
        return await self.record(**kwargs)


def test_register_delegates_to_auth_service():
    captured = {}

    class _Capturing(_FakeAuthService):
        async def create_user(self, user_data, is_superuser=False, commit=True):
            captured["called"] = True
            captured["is_superuser"] = is_superuser
            captured["commit"] = commit
            captured["username"] = user_data.username
            return _fake_user()

    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(auth_router, prefix="/auth")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_active_user] = lambda: _fake_user()
    app.dependency_overrides[get_auth_service] = lambda: _Capturing()
    app.dependency_overrides[get_audit_service] = lambda: _FakeAuditService()

    resp = TestClient(app, raise_server_exceptions=False).post(
        "/auth/register",
        json={"username": "bob", "email": "b@t.com", "password": "Str0ng!Pass"},
    )

    assert resp.status_code in (200, 201)
    assert captured.get("called") is True
    assert captured.get("is_superuser") is False
    assert captured.get("commit") is False
    assert captured.get("username") == "bob"


def test_register_weak_password_rejected():
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(auth_router, prefix="/auth")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_active_user] = lambda: _fake_user()
    app.dependency_overrides[get_auth_service] = lambda: _FakeAuthService()
    app.dependency_overrides[get_audit_service] = lambda: _FakeAuditService()

    resp = TestClient(app, raise_server_exceptions=False).post(
        "/auth/register",
        json={"username": "weak", "email": "w@t.com", "password": "123"},
    )
    assert resp.status_code == 422


def _build_login_app(auth_svc, audit_svc) -> FastAPI:
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(auth_router, prefix="/auth")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_auth_service] = lambda: auth_svc
    app.dependency_overrides[get_audit_service] = lambda: audit_svc
    return app


class _LoginAuthService:
    """模拟 authenticate / issue_token_pair 的登录用 AuthService。"""

    def __init__(self, user):
        self._user = user

    async def authenticate(self, username, password):
        return self._user

    async def issue_token_pair(self, user):
        return TokenPair(
            access_token="a", refresh_token="r", token_type="bearer", expires_in=60
        )


class _RecordingAuditService:
    def __init__(self):
        self.calls = []

    async def record(self, **kwargs):
        self.calls.append(kwargs)
        return None


def test_login_success_writes_audit():
    audit = _RecordingAuditService()
    auth = _LoginAuthService(_fake_user(is_superuser=False))
    client = TestClient(_build_login_app(auth, audit), raise_server_exceptions=False)

    resp = client.post("/auth/login", data={"username": "admin", "password": "x"})

    assert resp.status_code == 200
    assert [c["action"] for c in audit.calls] == ["auth.login"]
    assert audit.calls[0]["actor_username"] == "admin"


def test_login_failure_writes_audit():
    audit = _RecordingAuditService()
    auth = _LoginAuthService(None)  # 凭据错误
    client = TestClient(_build_login_app(auth, audit), raise_server_exceptions=False)

    resp = client.post("/auth/login", data={"username": "ghost", "password": "bad"})

    assert resp.status_code == 401
    assert [c["action"] for c in audit.calls] == ["auth.login_failed"]
    assert audit.calls[0]["detail"] == {"username": "ghost"}


def test_login_inactive_user_writes_audit():
    audit = _RecordingAuditService()
    inactive = _fake_user(is_superuser=False)
    inactive.is_active = False
    auth = _LoginAuthService(inactive)
    client = TestClient(_build_login_app(auth, audit), raise_server_exceptions=False)

    resp = client.post("/auth/login", data={"username": "admin", "password": "x"})

    assert resp.status_code == 401
    assert [c["action"] for c in audit.calls] == ["auth.login_failed"]
    assert audit.calls[0]["detail"]["reason"] == "user not active"
