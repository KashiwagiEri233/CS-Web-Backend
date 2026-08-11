"""AuthService.create_user 单元测试（不依赖真实数据库）。

验证 #2 修复：用户创建逻辑统一入口——查重、哈希、full_name 写入、is_superuser 控制。
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import (
    InvalidCredentialsException,
    RateLimitException,
    UserAlreadyExistsException,
    UserNotActiveException,
)
from app.core.security import hash_refresh_token
from app.core.timezone import now_utc
from app.services.auth_service import AuthService


@pytest.fixture
def auth_service(monkeypatch) -> AuthService:
    """构造 user_repo 被 AsyncMock 替换的 AuthService。

    绕开 __init__（避免实例化 RefreshTokenRepository 等真实依赖）。
    bcrypt 已在线程池包装；测试以 AsyncMock 替代耗时哈希。
    """
    monkeypatch.setattr(
        "app.services.auth_service.async_get_password_hash",
        AsyncMock(side_effect=lambda raw: f"hash:{raw}"),
    )
    db = MagicMock()
    db.commit = AsyncMock()  # service 层统一 commit
    svc = AuthService(db=db)  # ER-41：真实 __init__，不再绕
    svc.user_repo = AsyncMock()
    return svc


class _UserData:
    """模拟 schemas.auth.UserCreate 的最小形态。"""

    def __init__(
        self,
        username="u",
        email="e@t.com",
        password="secret",
        full_name=None,
        is_active=True,
    ):
        self.username = username
        self.email = email
        self.password = password
        self.full_name = full_name
        self.is_active = is_active


async def test_create_user_raises_on_duplicate_username(auth_service, monkeypatch):
    svc = auth_service
    svc.user_repo.get_by_username.return_value = MagicMock()

    with pytest.raises(UserAlreadyExistsException):
        await svc.create_user(_UserData())


async def test_create_user_raises_on_duplicate_email(auth_service, monkeypatch):
    svc = auth_service
    svc.user_repo.get_by_username.return_value = None
    svc.user_repo.get_by_email.return_value = MagicMock()

    with pytest.raises(UserAlreadyExistsException):
        await svc.create_user(_UserData())


async def test_create_user_hashes_password_and_persists(auth_service, monkeypatch):
    svc = auth_service
    svc.user_repo.get_by_username.return_value = None
    svc.user_repo.get_by_email.return_value = None
    svc.user_repo.create.return_value = "created"

    result = await svc.create_user(_UserData(username="bob", password="p@ss"))

    assert result == "created"
    # 传入 repo.create 的是 dict，且密码已被哈希
    passed = svc.user_repo.create.await_args.args[0]
    assert passed["username"] == "bob"
    assert passed["hashed_password"] == "hash:p@ss"
    assert passed["is_superuser"] is False


async def test_create_user_includes_full_name_when_provided(auth_service, monkeypatch):
    svc = auth_service
    svc.user_repo.get_by_username.return_value = None
    svc.user_repo.get_by_email.return_value = None

    await svc.create_user(_UserData(full_name="Bob Smith"))

    passed = svc.user_repo.create.await_args.args[0]
    assert passed["full_name"] == "Bob Smith"


async def test_create_user_omits_full_name_when_absent(auth_service, monkeypatch):
    svc = auth_service
    svc.user_repo.get_by_username.return_value = None
    svc.user_repo.get_by_email.return_value = None

    await svc.create_user(_UserData(full_name=None))

    passed = svc.user_repo.create.await_args.args[0]
    assert "full_name" not in passed


async def test_create_user_respects_is_superuser_flag(auth_service, monkeypatch):
    svc = auth_service
    svc.user_repo.get_by_username.return_value = None
    svc.user_repo.get_by_email.return_value = None

    await svc.create_user(_UserData(), is_superuser=True)

    passed = svc.user_repo.create.await_args.args[0]
    assert passed["is_superuser"] is True


async def test_refresh_loads_token_with_row_lock():
    db = MagicMock()
    db.commit = AsyncMock()
    svc = AuthService(db=db)  # ER-41：真实 __init__
    svc.refresh_repo = AsyncMock()
    svc.user_repo = AsyncMock()
    # 撤销时间远超宽限窗口 → 复用检测 → 吊销 family
    revoked = MagicMock(revoked_at=now_utc() - timedelta(days=1), family_id="family")
    svc.refresh_repo.get_by_hash.return_value = revoked

    with pytest.raises(InvalidCredentialsException):
        await svc.refresh_access_token("refresh-token")

    svc.refresh_repo.get_by_hash.assert_awaited_once_with(
        hash_refresh_token("refresh-token"), for_update=True
    )
    svc.refresh_repo.revoke_family.assert_awaited_once_with("family")


async def test_refresh_within_leeway_allows_concurrent_retry():
    """宽限窗口内 + family 仍有活跃后继：视为并发重试，放行轮换。"""
    db = MagicMock()
    db.commit = AsyncMock()
    svc = AuthService(db=db)  # ER-41：真实 __init__
    svc.refresh_repo = AsyncMock()
    svc.user_repo = AsyncMock()
    rotated = MagicMock(
        id=5,
        revoked_at=now_utc(),  # 刚被轮换撤销，处于宽限窗口内
        family_id="family",
        user_id=1,
        expires_at=now_utc() + timedelta(days=1),
    )
    svc.refresh_repo.get_by_hash.return_value = rotated
    svc.refresh_repo.family_has_active.return_value = True
    svc.user_repo.get_by_id.return_value = MagicMock(
        id=1, username="u", is_active=True, deleted_at=None, password_changed_at=None
    )

    pair = await svc.refresh_access_token("refresh-token")

    assert pair.access_token and pair.refresh_token
    svc.refresh_repo.revoke_family.assert_not_called()
    # 不刷新 revoked_at，宽限窗口不被延长
    svc.refresh_repo.revoke.assert_not_called()
    assert svc.refresh_repo.create.await_args.kwargs["family_id"] == "family"


async def test_refresh_revoked_without_active_family_is_reuse():
    """宽限时间内但 family 已无活跃 token（整体撤销）→ 仍按复用处置。"""
    db = MagicMock()
    db.commit = AsyncMock()
    svc = AuthService(db=db)  # ER-41：真实 __init__
    svc.refresh_repo = AsyncMock()
    svc.user_repo = AsyncMock()
    revoked = MagicMock(
        revoked_at=now_utc(),
        family_id="family",
        user_id=1,
        expires_at=now_utc() + timedelta(days=1),
    )
    svc.refresh_repo.get_by_hash.return_value = revoked
    svc.refresh_repo.family_has_active.return_value = False

    with pytest.raises(InvalidCredentialsException):
        await svc.refresh_access_token("refresh-token")

    svc.refresh_repo.revoke_family.assert_awaited_once_with("family")


async def test_authenticate_missing_user_still_verifies_dummy_hash(auth_service, monkeypatch):
    svc = auth_service
    svc.user_repo.get_by_username.return_value = None
    verify = AsyncMock(return_value=False)
    monkeypatch.setattr("app.services.auth_service.async_verify_password", verify)

    assert await svc.authenticate("missing", "Password1!") is None
    verify.assert_awaited_once()
    assert verify.call_args.args[0] == "Password1!"


def test_password_change_claim_keeps_microsecond_precision():
    user = MagicMock(
        username="alice",
        id=7,
        password_changed_at=datetime(
            2026, 7, 14, 12, 0, 0, 123456, tzinfo=timezone.utc
        ),
    )

    claims = AuthService._access_token_claims(user)

    assert claims["pwd_at"] == 1784030400123456


# ---- login（编排：防爆破 → 凭据 → 激活 → 签发 + 审计） ----


def _make_login_service(monkeypatch, *, limiter_allowed: bool = True):
    """构造可测 login 的 AuthService：限流/审计/签发全部 mock。"""
    db = MagicMock()
    db.commit = AsyncMock()
    svc = AuthService(db=db)  # ER-41：真实 __init__，不再绕
    svc.user_repo = AsyncMock()
    svc.audit = AsyncMock()

    limiter = AsyncMock()
    limiter.is_allowed.return_value = limiter_allowed
    monkeypatch.setattr("app.services.auth_service.get_limiter", lambda: limiter)

    issue = AsyncMock(return_value="pair")
    monkeypatch.setattr(AuthService, "issue_token_pair", issue)
    return svc, limiter, issue


def _active_user():
    return MagicMock(id=1, username="admin", is_active=True)


async def test_login_success_issues_pair_and_writes_audit(auth_service, monkeypatch):
    svc, _limiter, issue = _make_login_service(monkeypatch)
    monkeypatch.setattr(
        AuthService, "authenticate", AsyncMock(return_value=_active_user())
    )

    pair = await svc.login("admin", "x", {"ip_address": "127.0.0.1"})

    assert pair == "pair"
    issue.assert_awaited_once()
    actions = [c.kwargs["action"] for c in svc.audit.record.await_args_list]
    assert actions == ["auth.login"]


async def test_login_bad_credentials_raises_and_audits(auth_service, monkeypatch):
    svc, _limiter, issue = _make_login_service(monkeypatch)
    monkeypatch.setattr(AuthService, "authenticate", AsyncMock(return_value=None))

    with pytest.raises(InvalidCredentialsException):
        await svc.login("ghost", "bad", {})

    issue.assert_not_called()
    actions = [c.kwargs["action"] for c in svc.audit.record.await_args_list]
    assert actions == ["auth.login_failed"]


async def test_login_inactive_user_raises_and_audits(auth_service, monkeypatch):
    svc, _limiter, issue = _make_login_service(monkeypatch)
    monkeypatch.setattr(
        AuthService,
        "authenticate",
        AsyncMock(return_value=MagicMock(id=1, username="u", is_active=False)),
    )

    with pytest.raises(UserNotActiveException):
        await svc.login("u", "x", {})

    issue.assert_not_called()
    last = svc.audit.record.await_args_list[-1].kwargs
    assert last["action"] == "auth.login_failed"
    assert last["detail"]["reason"] == "user not active"


async def test_login_rate_limited_per_account(auth_service, monkeypatch):
    """账号级限流触发：不验证凭据、不签发，直接 429 并写审计。"""
    svc, limiter, issue = _make_login_service(monkeypatch, limiter_allowed=False)
    authenticate = AsyncMock()
    monkeypatch.setattr(AuthService, "authenticate", authenticate)

    with pytest.raises(RateLimitException):
        await svc.login("victim", "x", {})

    authenticate.assert_not_called()
    issue.assert_not_called()
    assert limiter.is_allowed.await_args.args[0] == "ratelimit:auth_account:victim"
    actions = [c.kwargs["action"] for c in svc.audit.record.await_args_list]
    assert actions == ["auth.login_rate_limited"]
