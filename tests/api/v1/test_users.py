"""用户路由端到端测试（不依赖数据库）。

通过覆盖鉴权依赖 + 替换 UserService 为假实现，验证：
- GET /users 返回统一分页结构 {items,total,skip,limit} 并尊重 skip/limit；
- 未鉴权访问被拒（不返回 200）。
"""

import types

from fastapi import FastAPI
from starlette.testclient import TestClient

import app.api.v1.users as users_module
from app.api.v1.users import router as users_router
from app.core.exceptions import setup_exception_handlers
from app.database import get_db
from app.dependencies import get_current_superuser

_TOTAL = 30


def _fake_user(i: int):
    return types.SimpleNamespace(
        id=i,
        username=f"user{i:03d}",
        email=f"u{i}@t.com",
        full_name=None,
        is_active=True,
        is_superuser=False,
    )


class _FakeUserService:
    """假 UserService：不接触数据库，按 skip/limit 切片返回。"""

    def __init__(self, db):
        pass

    async def list_users(self, skip: int = 0, limit: int = 100):
        users = [_fake_user(i) for i in range(skip, min(skip + limit, _TOTAL))]
        return users, _TOTAL


def _client_authed(monkeypatch):
    monkeypatch.setattr(users_module, "UserService", _FakeUserService)
    app = FastAPI()
    app.include_router(users_router, prefix="/users")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_superuser] = lambda: _fake_user(1)
    return TestClient(app)


def test_list_users_paginated(monkeypatch):
    resp = _client_authed(monkeypatch).get("/users/?skip=0&limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "total", "skip", "limit"}
    assert body["total"] == _TOTAL
    assert body["skip"] == 0 and body["limit"] == 10
    assert len(body["items"]) == 10
    assert body["items"][0]["username"] == "user000"


def test_list_users_default_pagination(monkeypatch):
    # 不带查询参数 → PaginationParams 默认 skip=0/limit=100（经真实依赖注入解析）
    body = _client_authed(monkeypatch).get("/users/").json()
    assert body["skip"] == 0 and body["limit"] == 100
    assert len(body["items"]) == _TOTAL  # 30 < 100，全部返回


def test_list_users_respects_skip(monkeypatch):
    resp = _client_authed(monkeypatch).get("/users/?skip=25&limit=10")
    body = resp.json()
    # 共 30 条，从 25 开始最多剩 5 条
    assert len(body["items"]) == 5
    assert body["skip"] == 25


def test_list_users_limit_validation(monkeypatch):
    # limit 超过上限 500 应被 422 拒绝
    resp = _client_authed(monkeypatch).get("/users/?limit=99999")
    assert resp.status_code == 422


def test_list_users_requires_auth():
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(users_router, prefix="/users")
    resp = TestClient(app, raise_server_exceptions=False).get("/users/")
    # 未提供凭证：必须被拒（401/403），绝不能放行返回 200
    assert resp.status_code != 200


def test_update_user_password_revokes_refresh_tokens(monkeypatch):
    """改密成功后应撤销该用户全部 refresh token（安全：作废旧会话）。"""
    revoked = {"user_id": None}

    class _FakeUserService:
        def __init__(self, db):
            pass

        async def update_user(self, user_id, update_data):
            return _fake_user(user_id)

    class _FakeAuthService:
        def __init__(self, db):
            pass

        async def revoke_all_user_tokens(self, user_id):
            revoked["user_id"] = user_id
            return 1

    monkeypatch.setattr(users_module, "UserService", _FakeUserService)
    monkeypatch.setattr(users_module, "AuthService", _FakeAuthService)

    app = FastAPI()
    app.include_router(users_router, prefix="/users")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_superuser] = lambda: _fake_user(1)

    resp = TestClient(app, raise_server_exceptions=False).put(
        "/users/5",
        json={"password": "NewStr0ng!Pass"},
    )
    assert resp.status_code == 200
    assert revoked["user_id"] == 5


def test_update_user_without_password_keeps_tokens(monkeypatch):
    """非改密更新（如改邮箱）不应撤销 refresh token。"""
    revoked = {"called": False}

    class _FakeUserService:
        def __init__(self, db):
            pass

        async def update_user(self, user_id, update_data):
            return _fake_user(user_id)

    class _FakeAuthService:
        def __init__(self, db):
            pass

        async def revoke_all_user_tokens(self, user_id):
            revoked["called"] = True
            return 0

    monkeypatch.setattr(users_module, "UserService", _FakeUserService)
    monkeypatch.setattr(users_module, "AuthService", _FakeAuthService)

    app = FastAPI()
    app.include_router(users_router, prefix="/users")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_superuser] = lambda: _fake_user(1)

    resp = TestClient(app, raise_server_exceptions=False).put(
        "/users/5",
        json={"email": "new@t.com"},
    )
    assert resp.status_code == 200
    assert revoked["called"] is False
