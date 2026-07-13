"""审计查询 API 测试（不依赖数据库）。"""

import types
from datetime import datetime, timezone

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.api.v1.audit import router as audit_router
from app.core.exceptions import setup_exception_handlers
from app.database import get_db
from app.dependencies import get_current_active_user
from app.dependencies_services import get_audit_service
from app.services.audit_service import AuditService


def _fake_user(is_superuser=True):
    return types.SimpleNamespace(
        id=1,
        username="admin",
        email="a@t.com",
        full_name=None,
        is_active=True,
        is_superuser=is_superuser,
    )


class _FakeAuditService:
    def __init__(self, db=None):
        pass

    async def list_logs(self, **kwargs):
        row = types.SimpleNamespace(
            id=1,
            actor_id=1,
            actor_username="admin",
            action="user.create",
            resource_type="user",
            resource_id="9",
            detail={"username": "bob"},
            ip_address="127.0.0.1",
            user_agent="test",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        return [row], 1

    async def get_log(self, log_id):
        if log_id != 1:
            return None
        return types.SimpleNamespace(
            id=1,
            actor_id=1,
            actor_username="admin",
            action="user.create",
            resource_type="user",
            resource_id="9",
            detail=None,
            ip_address=None,
            user_agent=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def to_item_dict(self, row):
        return AuditService.to_item_dict(row)


def _client():
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(audit_router, prefix="/audit")

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_active_user] = lambda: _fake_user()
    app.dependency_overrides[get_audit_service] = lambda: _FakeAuditService()
    return TestClient(app, raise_server_exceptions=False)


def test_list_audit_logs_paginated():
    resp = _client().get("/audit/logs?skip=0&limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "total", "skip", "limit"}
    assert body["total"] == 1
    assert body["items"][0]["action"] == "user.create"


def test_get_audit_log_detail():
    resp = _client().get("/audit/logs/1")
    assert resp.status_code == 200
    assert resp.json()["id"] == 1


def test_get_audit_log_not_found():
    resp = _client().get("/audit/logs/99")
    assert resp.status_code == 404


def test_audit_requires_auth():
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(audit_router, prefix="/audit")
    resp = TestClient(app, raise_server_exceptions=False).get("/audit/logs")
    assert resp.status_code != 200
