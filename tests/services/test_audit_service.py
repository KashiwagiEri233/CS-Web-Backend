"""审计写入的事务策略测试。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.audit_service import AuditService


async def test_strict_shared_audit_rolls_back_and_propagates_failure():
    db = MagicMock()
    db.rollback = AsyncMock()
    svc = AuditService(db)
    svc._write = AsyncMock(side_effect=RuntimeError("audit failed"))

    with pytest.raises(RuntimeError, match="audit failed"):
        await svc.record(
            action="user.update",
            resource_type="user",
            use_shared_session=True,
            strict=True,
        )

    db.rollback.assert_awaited_once()


async def test_default_audit_remains_best_effort():
    svc = AuditService()
    svc._write = AsyncMock(side_effect=RuntimeError("audit failed"))

    assert await svc.record(action="read", resource_type="thing") is None


async def test_record_atomic_requires_shared_session():
    svc = AuditService()

    with pytest.raises(RuntimeError, match="共享 AsyncSession"):
        await svc.record_atomic(action="user.update", resource_type="user")


async def test_record_atomic_uses_strict_shared_commit(monkeypatch):
    db = MagicMock()
    svc = AuditService(db)
    row = MagicMock()
    record = AsyncMock(return_value=row)
    monkeypatch.setattr(svc, "record", record)

    result = await svc.record_atomic(
        action="user.update",
        resource_type="user",
        resource_id="7",
    )

    assert result is row
    record.assert_awaited_once_with(
        action="user.update",
        resource_type="user",
        resource_id="7",
        actor_id=None,
        actor_username=None,
        detail=None,
        ip_address=None,
        user_agent=None,
        commit=True,
        use_shared_session=True,
        strict=True,
    )
