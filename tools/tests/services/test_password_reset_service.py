"""PasswordResetService 单元测试（不依赖真实数据库）。

覆盖 create/list/approve/reject 及内部 _get_pending_or_raise /
_revoke_user_refresh_tokens：申请去重、审批守卫（用户不存在 / SELF_APPROVE /
默认密码未配置 / 已处理）、成功路径的密码重置 + token 撤销 + 审计写入。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ErrorCode,
    NotFoundException,
)
from app.services.password_reset_service import PasswordResetService


def _make_service(
    monkeypatch, default_password: str = "DefaultPass123!"
) -> PasswordResetService:
    """构造 repo/user_repo/audit 被 AsyncMock 替换的 PasswordResetService。

    服务在调用点读取 settings.PASSWORD_RESET_DEFAULT，这里通过 monkeypatch
    注入可控的 mock settings；async_get_password_hash 同样在服务模块侧打桩，
    避免触发真实 bcrypt。
    """
    monkeypatch.setattr(
        "app.services.password_reset_service.async_get_password_hash",
        AsyncMock(side_effect=lambda raw: f"hash:{raw}"),
    )
    mock_settings = MagicMock()
    mock_settings.PASSWORD_RESET_DEFAULT = default_password
    monkeypatch.setattr("app.services.password_reset_service.settings", mock_settings)

    db = MagicMock()
    db.commit = AsyncMock()
    svc = PasswordResetService(db=db)  # ER-41：真实 __init__，不再绕
    svc.repo = AsyncMock()
    svc.user_repo = AsyncMock()
    svc.audit = AsyncMock()
    # service 重构后 approve/reject 不再提前 commit，改由 audit.record_atomic
    # 同事务原子提交审计（见 service 内注释）；需显式设为 AsyncMock 方可 await+断言。
    svc.audit.record_atomic = AsyncMock()
    return svc


def _patch_refresh_token_repo(monkeypatch) -> AsyncMock:
    """打桩 _revoke_user_refresh_tokens 内部 import 的 RefreshTokenRepository。

    方法体内 `from app.repositories.refresh_token_repo import RefreshTokenRepository`
    后 `RefreshTokenRepository(self.db).revoke_all_for_user(user_id)`，故把类替换为
    返回带 async revoke_all_for_user 实例的 MagicMock。
    """
    instance = AsyncMock()
    instance.revoke_all_for_user = AsyncMock(return_value=0)
    monkeypatch.setattr(
        "app.repositories.refresh_token_repo.RefreshTokenRepository",
        MagicMock(return_value=instance),
    )
    return instance


# ---- create_request ----


async def test_create_request_returns_existing_id_when_pending(monkeypatch):
    svc = _make_service(monkeypatch)
    existing = MagicMock(id=42)
    svc.repo.get_pending_for_email.return_value = existing

    result = await svc.create_request("U@T.COM")

    assert result == {"id": 42}
    svc.repo.get_pending_for_email.assert_awaited_once_with("u@t.com")
    svc.repo.create.assert_not_called()
    svc.db.commit.assert_not_called()


async def test_create_request_creates_new_when_no_pending(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.repo.get_pending_for_email.return_value = None
    new_req = MagicMock(id=7)
    svc.repo.create.return_value = new_req

    result = await svc.create_request("U@T.COM")

    assert result == {"id": 7}
    svc.repo.get_pending_for_email.assert_awaited_once_with("u@t.com")
    svc.repo.create.assert_awaited_once_with("u@t.com")
    svc.db.commit.assert_awaited_once()


# ---- list_requests ----


async def test_list_requests_delegates_to_repo(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.repo.list.return_value = ["r1", "r2"]

    result = await svc.list_requests(status="pending")

    assert result == ["r1", "r2"]
    svc.repo.list.assert_awaited_once_with("pending")


# ---- approve_request：守卫 ----


async def test_approve_request_raises_when_user_missing(monkeypatch):
    svc = _make_service(monkeypatch)
    req = MagicMock(id=10, email="u@t.com", status="pending")
    svc.repo.get_by_id.return_value = req
    svc.user_repo.get_by_email.return_value = None

    with pytest.raises(NotFoundException):
        await svc.approve_request(10, admin_id=99, admin_username="admin")

    svc.db.commit.assert_not_called()
    svc.audit.record.assert_not_called()


async def test_approve_request_blocks_self_approve(monkeypatch):
    svc = _make_service(monkeypatch)
    req = MagicMock(id=10, email="u@t.com", status="pending")
    svc.repo.get_by_id.return_value = req
    # admin_id == user.id → SELF_APPROVE
    user = MagicMock(id=99, email="u@t.com")
    svc.user_repo.get_by_email.return_value = user

    with pytest.raises(AuthorizationException) as exc:
        await svc.approve_request(10, admin_id=99, admin_username="admin")

    assert exc.value.error_code == ErrorCode.Authorization.SELF_APPROVE
    svc.db.commit.assert_not_called()
    svc.audit.record.assert_not_called()


async def test_approve_request_raises_when_default_password_not_configured(monkeypatch):
    svc = _make_service(monkeypatch, default_password=None)
    req = MagicMock(id=10, email="u@t.com", status="pending")
    svc.repo.get_by_id.return_value = req
    user = MagicMock(id=5, email="u@t.com")
    svc.user_repo.get_by_email.return_value = user

    with pytest.raises(ConflictException) as exc:
        await svc.approve_request(10, admin_id=99, admin_username="admin")

    assert exc.value.error_code == ErrorCode.Validation.PASSWORD_RESET_NOT_CONFIGURED
    svc.db.commit.assert_not_called()
    svc.audit.record.assert_not_called()


async def test_approve_request_raises_when_already_processed(monkeypatch):
    svc = _make_service(monkeypatch)
    req = MagicMock(id=10, email="u@t.com", status="approved")
    svc.repo.get_by_id.return_value = req

    with pytest.raises(ConflictException) as exc:
        await svc.approve_request(10, admin_id=99, admin_username="admin")

    assert exc.value.error_code == ErrorCode.Validation.ALREADY_PROCESSED
    # 状态非 pending 时不应再查用户
    svc.user_repo.get_by_email.assert_not_called()
    svc.db.commit.assert_not_called()


# ---- approve_request：成功路径 ----


async def test_approve_request_resets_password_and_revokes_tokens(monkeypatch):
    refresh_repo = _patch_refresh_token_repo(monkeypatch)
    svc = _make_service(monkeypatch)
    req = MagicMock(id=10, email="u@t.com", status="pending")
    svc.repo.get_by_id.return_value = req
    user = MagicMock(id=5, email="u@t.com", hashed_password="old")
    svc.user_repo.get_by_email.return_value = user

    result = await svc.approve_request(
        10, admin_id=99, admin_username="admin", note="ok"
    )

    assert result is req
    assert user.hashed_password == "hash:DefaultPass123!"
    assert user.password_changed_at is not None
    assert user.updated_at is not None
    refresh_repo.revoke_all_for_user.assert_awaited_once_with(5)
    svc.repo.resolve.assert_awaited_once_with(
        request=req, status="approved", admin_id=99, admin_note="ok"
    )
    # service 重构：不再提前 commit，改由 audit.record_atomic 原子提交审计
    svc.audit.record_atomic.assert_awaited_once()


async def test_approve_request_records_audit_on_success(monkeypatch):
    _patch_refresh_token_repo(monkeypatch)
    svc = _make_service(monkeypatch)
    req = MagicMock(id=10, email="u@t.com", status="pending")
    svc.repo.get_by_id.return_value = req
    user = MagicMock(id=5, email="u@t.com")
    svc.user_repo.get_by_email.return_value = user

    await svc.approve_request(
        10,
        admin_id=99,
        admin_username="admin",
        note="ok",
        client_meta={"ip_address": "1.2.3.4", "user_agent": "ua"},
    )

    svc.audit.record_atomic.assert_awaited_once_with(
        action="password_reset.approve",
        resource_type="password_reset_request",
        resource_id="10",
        actor_id=99,
        actor_username="admin",
        detail={"email": "u@t.com", "note": "ok"},
        ip_address="1.2.3.4",
        user_agent="ua",
    )


# ---- reject_request ----


async def test_reject_request_updates_status_and_records_audit(monkeypatch):
    svc = _make_service(monkeypatch)
    req = MagicMock(id=10, email="u@t.com", status="pending")
    svc.repo.get_by_id.return_value = req

    result = await svc.reject_request(
        10, admin_id=99, admin_username="admin", note="nope"
    )

    assert result is req
    svc.repo.resolve.assert_awaited_once_with(
        request=req, status="rejected", admin_id=99, admin_note="nope"
    )
    svc.audit.record_atomic.assert_awaited_once()
    svc.audit.record_atomic.assert_awaited_once_with(
        action="password_reset.reject",
        resource_type="password_reset_request",
        resource_id="10",
        actor_id=99,
        actor_username="admin",
        detail={"email": "u@t.com", "note": "nope"},
    )


# ---- _get_pending_or_raise ----


async def test_get_pending_or_raise_raises_when_missing(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.repo.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await svc._get_pending_or_raise(99)

    svc.repo.get_by_id.assert_awaited_once_with(99)


async def test_get_pending_or_raise_raises_when_not_pending(monkeypatch):
    svc = _make_service(monkeypatch)
    req = MagicMock(id=99, status="rejected")
    svc.repo.get_by_id.return_value = req

    with pytest.raises(ConflictException) as exc:
        await svc._get_pending_or_raise(99)

    assert exc.value.error_code == ErrorCode.Validation.ALREADY_PROCESSED
