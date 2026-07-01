"""RBAC 路由端到端测试（不依赖数据库）。

通过覆盖鉴权依赖 + 替换 RBACService 为假实现，验证：
- GET /rbac/roles 与 /rbac/permissions 返回统一分页结构 {items,total,skip,limit}；
- GET /rbac/me/permissions 返回当前用户权限集合；
- 未鉴权访问被拒。
"""

import types

from fastapi import FastAPI
from starlette.testclient import TestClient

import app.api.v1.rbac as rbac_module
from app.api.v1.rbac import router as rbac_router
from app.core.exceptions import setup_exception_handlers
from app.database import get_db
from app.dependencies import get_current_active_user, get_current_superuser


def _fake_user(user_id=1, is_superuser=False):
    return types.SimpleNamespace(
        id=user_id, username="admin", email="a@t.com",
        full_name=None, is_active=True, is_superuser=is_superuser,
    )


def _roles_payload(n):
    return [
        types.SimpleNamespace(
            id=i, name=f"role{i}", description=None, is_active=True,
            permissions=[], created_at=None, updated_at=None,
        )
        for i in range(n)
    ]


class _FakeRBACService:
    """假 RBACService：不接触数据库。"""

    def __init__(self, db):
        pass

    async def get_all_roles(self, skip=0, limit=None):
        return _roles_payload(min(limit or 0, 30))[skip:skip + (limit or 0)]

    async def count_roles(self):
        return 30

    async def get_all_permissions(self, skip=0, limit=None):
        return []

    async def count_permissions(self):
        return 0

    async def get_user_permissions(self, user_id):
        return {"user:read", "role:read"}

    async def get_user_roles(self, user_id):
        return _roles_payload(1)


def _client(monkeypatch, *, authed=True, superuser=True):
    monkeypatch.setattr(rbac_module, "RBACService", _FakeRBACService)
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(rbac_router, prefix="/rbac")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    if authed:
        app.dependency_overrides[get_current_superuser] = lambda: _fake_user(is_superuser=superuser)
        app.dependency_overrides[get_current_active_user] = lambda: _fake_user(is_superuser=superuser)
    return TestClient(app, raise_server_exceptions=False)


def test_get_roles_paginated(monkeypatch):
    resp = _client(monkeypatch).get("/rbac/roles/?skip=0&limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "total", "skip", "limit"}
    assert body["total"] == 30
    assert body["skip"] == 0 and body["limit"] == 5
    assert len(body["items"]) == 5


def test_get_permissions_paginated_structure(monkeypatch):
    resp = _client(monkeypatch).get("/rbac/permissions/?skip=0&limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "total", "skip", "limit"}
    assert body["total"] == 0


def test_get_my_permissions_non_superuser(monkeypatch):
    # 非超管：走 RBACService.get_user_permissions
    resp = _client(monkeypatch, superuser=False).get("/rbac/me/permissions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == 1
    assert set(body["permissions"]) == {"user:read", "role:read"}


def test_get_my_permissions_superuser_wildcard(monkeypatch):
    # 超管：端点以通配符 *:* 表示全部权限
    resp = _client(monkeypatch, superuser=True).get("/rbac/me/permissions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["permissions"] == ["*:*"]


def test_get_my_roles(monkeypatch):
    resp = _client(monkeypatch).get("/rbac/me/roles")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body[0]["name"] == "role0"


def test_roles_requires_auth(monkeypatch):
    # 不注入 superuser 依赖 → 未鉴权应被拒
    monkeypatch.setattr(rbac_module, "RBACService", _FakeRBACService)
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(rbac_router, prefix="/rbac")
    resp = TestClient(app, raise_server_exceptions=False).get("/rbac/roles/")
    assert resp.status_code != 200
