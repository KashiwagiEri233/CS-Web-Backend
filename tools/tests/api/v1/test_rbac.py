"""RBAC 路由端到端测试（不依赖数据库）。

通过覆盖 get_rbac_service / 鉴权依赖 + 假 RBACService，验证分页与 me 接口。
"""

import types

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.api.v1.rbac import router as rbac_router
from app.core.exceptions import setup_exception_handlers
from app.database import get_db
from app.dependencies import get_current_active_user
from app.dependencies_services import get_audit_service, get_rbac_service


def _fake_user(user_id=1, is_superuser=False):
    return types.SimpleNamespace(
        id=user_id,
        username="admin",
        email="a@t.com",
        full_name=None,
        is_active=True,
        is_superuser=is_superuser,
    )


def _roles_payload(n):
    return [
        types.SimpleNamespace(
            id=i,
            name=f"role{i}",
            description=None,
            is_active=True,
            permissions=[],
            created_at=None,
            updated_at=None,
        )
        for i in range(n)
    ]


class _FakeRBACService:
    def __init__(self, db=None):
        pass

    async def get_all_roles(self, skip=0, limit=None):
        return _roles_payload(min(limit or 0, 30))[skip : skip + (limit or 0)]

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


class _FakeAuditService:
    def __init__(self, db=None):
        pass

    async def record(self, **kwargs):
        return None

    async def record_atomic(self, **kwargs):
        return await self.record(**kwargs)


def _client(*, authed=True, superuser=True):
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(rbac_router, prefix="/rbac")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_rbac_service] = lambda: _FakeRBACService()
    app.dependency_overrides[get_audit_service] = lambda: _FakeAuditService()
    if authed:
        app.dependency_overrides[get_current_active_user] = lambda: _fake_user(
            is_superuser=superuser
        )
    return TestClient(app, raise_server_exceptions=False)


def test_get_roles_paginated():
    resp = _client().get("/rbac/roles/?skip=0&limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "total", "skip", "limit"}
    assert body["total"] == 30
    assert body["skip"] == 0 and body["limit"] == 5
    assert len(body["items"]) == 5


def test_get_permissions_paginated_structure():
    resp = _client().get("/rbac/permissions/?skip=0&limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "total", "skip", "limit"}
    assert body["total"] == 0


def test_get_my_permissions_non_superuser():
    resp = _client(superuser=False).get("/rbac/me/permissions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == 1
    assert set(body["permissions"]) == {"user:read", "role:read"}


def test_get_my_permissions_superuser_wildcard():
    resp = _client(superuser=True).get("/rbac/me/permissions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["permissions"] == ["*:*"]


def test_get_my_roles():
    resp = _client().get("/rbac/me/roles")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body[0]["name"] == "role0"


def test_roles_requires_auth():
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(rbac_router, prefix="/rbac")
    app.dependency_overrides[get_rbac_service] = lambda: _FakeRBACService()
    resp = TestClient(app, raise_server_exceptions=False).get("/rbac/roles/")
    assert resp.status_code != 200
