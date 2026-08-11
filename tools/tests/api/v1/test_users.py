"""用户路由端到端测试（不依赖数据库）。"""

import types

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.api.v1.users import router as users_router
from app.core.exceptions import setup_exception_handlers
from app.database import get_db
from app.dependencies import get_current_active_user
from app.dependencies_services import (
    get_audit_service,
    get_auth_service,
    get_user_service,
)

_TOTAL = 30


def _fake_user(i: int = 1, is_superuser: bool = True):
    return types.SimpleNamespace(
        id=i,
        username=f"user{i:03d}",
        email=f"u{i}@t.com",
        full_name=None,
        is_active=True,
        is_superuser=is_superuser,
    )


class _FakeUserService:
    def __init__(self, db=None):
        pass

    async def list_users(self, skip: int = 0, limit: int = 100):
        users = [_fake_user(i) for i in range(skip, min(skip + limit, _TOTAL))]
        return users, _TOTAL

    async def update_user(self, user_id, update_data, commit=True, actor=None):
        return _fake_user(user_id)

    async def update_profile(self, user, update_data):
        return user

    async def delete_user(self, user_id, actor, commit=True):
        return None

    async def get_user(self, user_id):
        return _fake_user(user_id)


class _FakeAuthService:
    def __init__(self, db=None):
        pass

    async def create_user(self, user_data, is_superuser=False):
        return _fake_user(99, is_superuser=is_superuser)


class _FakeAuditService:
    def __init__(self, db=None):
        pass

    async def record(self, **kwargs):
        return None

    async def record_atomic(self, **kwargs):
        return await self.record(**kwargs)


def _client_authed(monkeypatch):
    app = FastAPI()
    app.include_router(users_router, prefix="/users")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_active_user] = lambda: _fake_user(
        1, is_superuser=True
    )
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService()
    app.dependency_overrides[get_auth_service] = lambda: _FakeAuthService()
    app.dependency_overrides[get_audit_service] = lambda: _FakeAuditService()
    return TestClient(app)


def test_list_users_paginated(monkeypatch):
    resp = _client_authed(monkeypatch).get("/users/?skip=0&limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "total", "skip", "limit", "total_pages"}
    assert body["total"] == _TOTAL
    assert body["skip"] == 0 and body["limit"] == 10
    assert len(body["items"]) == 10


def test_list_users_default_pagination(monkeypatch):
    body = _client_authed(monkeypatch).get("/users/").json()
    assert body["skip"] == 0 and body["limit"] == 100
    assert len(body["items"]) == _TOTAL


def test_list_users_respects_skip(monkeypatch):
    resp = _client_authed(monkeypatch).get("/users/?skip=25&limit=10")
    body = resp.json()
    assert len(body["items"]) == 5
    assert body["skip"] == 25


def test_list_users_limit_validation(monkeypatch):
    resp = _client_authed(monkeypatch).get("/users/?limit=99999")
    assert resp.status_code == 422


def test_list_users_requires_auth():
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(users_router, prefix="/users")
    resp = TestClient(app, raise_server_exceptions=False).get("/users/")
    assert resp.status_code != 200


def test_update_user_password_calls_service(monkeypatch):
    """改密走 UserService.update_user（内部同事务撤 refresh）。"""
    called = {"data": None}

    class _Capturing(_FakeUserService):
        async def update_user(self, user_id, update_data, commit=True, actor=None):
            called["data"] = (user_id, update_data)
            called["commit"] = commit
            return _fake_user(user_id)

    app = FastAPI()
    app.include_router(users_router, prefix="/users")
    app.dependency_overrides[get_db] = lambda: (_ for _ in (None,))

    # fix async generator
    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_active_user] = lambda: _fake_user(
        1, is_superuser=True
    )
    app.dependency_overrides[get_user_service] = lambda: _Capturing()
    app.dependency_overrides[get_audit_service] = lambda: _FakeAuditService()

    resp = TestClient(app, raise_server_exceptions=False).put(
        "/users/5",
        json={"password": "NewStr0ng!Pass"},
    )
    assert resp.status_code == 200
    assert called["data"][0] == 5
    assert "password" in called["data"][1]
    assert called["commit"] is False


def test_update_user_without_password(monkeypatch):
    called = {"data": None}

    class _Capturing(_FakeUserService):
        async def update_user(self, user_id, update_data, commit=True, actor=None):
            called["data"] = update_data
            called["commit"] = commit
            return _fake_user(user_id)

    app = FastAPI()
    app.include_router(users_router, prefix="/users")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_active_user] = lambda: _fake_user(
        1, is_superuser=True
    )
    app.dependency_overrides[get_user_service] = lambda: _Capturing()
    app.dependency_overrides[get_audit_service] = lambda: _FakeAuditService()

    resp = TestClient(app, raise_server_exceptions=False).put(
        "/users/5",
        json={"email": "new@t.com"},
    )
    assert resp.status_code == 200
    assert called["data"] == {"email": "new@t.com"}
    assert called["commit"] is False


def test_update_me_matches_static_route(monkeypatch):
    """静态 /me 必须优先于 /{user_id}，避免把 me 当整数解析。"""
    resp = _client_authed(monkeypatch).put(
        "/users/me", json={"full_name": "Updated Name"}
    )
    assert resp.status_code == 200
