"""AuthService.create_user 单元测试（不依赖真实数据库）。

验证 #2 修复：用户创建逻辑统一入口——查重、哈希、full_name 写入、is_superuser 控制。
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import InvalidCredentialsException, UserAlreadyExistsException
from app.core.security import hash_refresh_token
from app.services.auth_service import AuthService


def _make_auth_service(monkeypatch) -> AuthService:
    """构造 user_repo 被 AsyncMock 替换的 AuthService。

    绕开 __init__（避免实例化 RefreshTokenRepository 等真实依赖）。
    bcrypt 已在线程池包装；测试以 AsyncMock 替代耗时哈希。
    """
    monkeypatch.setattr(
        "app.services.auth_service.async_get_password_hash",
        AsyncMock(side_effect=lambda raw: f"hash:{raw}"),
    )
    svc = AuthService.__new__(AuthService)
    svc.db = MagicMock()
    svc.db.commit = AsyncMock()  # service 层统一 commit
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


async def test_create_user_raises_on_duplicate_username(monkeypatch):
    svc = _make_auth_service(monkeypatch)
    svc.user_repo.get_by_username.return_value = MagicMock()

    with pytest.raises(UserAlreadyExistsException):
        await svc.create_user(_UserData())


async def test_create_user_raises_on_duplicate_email(monkeypatch):
    svc = _make_auth_service(monkeypatch)
    svc.user_repo.get_by_username.return_value = None
    svc.user_repo.get_by_email.return_value = MagicMock()

    with pytest.raises(UserAlreadyExistsException):
        await svc.create_user(_UserData())


async def test_create_user_hashes_password_and_persists(monkeypatch):
    svc = _make_auth_service(monkeypatch)
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


async def test_create_user_includes_full_name_when_provided(monkeypatch):
    svc = _make_auth_service(monkeypatch)
    svc.user_repo.get_by_username.return_value = None
    svc.user_repo.get_by_email.return_value = None

    await svc.create_user(_UserData(full_name="Bob Smith"))

    passed = svc.user_repo.create.await_args.args[0]
    assert passed["full_name"] == "Bob Smith"


async def test_create_user_omits_full_name_when_absent(monkeypatch):
    svc = _make_auth_service(monkeypatch)
    svc.user_repo.get_by_username.return_value = None
    svc.user_repo.get_by_email.return_value = None

    await svc.create_user(_UserData(full_name=None))

    passed = svc.user_repo.create.await_args.args[0]
    assert "full_name" not in passed


async def test_create_user_respects_is_superuser_flag(monkeypatch):
    svc = _make_auth_service(monkeypatch)
    svc.user_repo.get_by_username.return_value = None
    svc.user_repo.get_by_email.return_value = None

    await svc.create_user(_UserData(), is_superuser=True)

    passed = svc.user_repo.create.await_args.args[0]
    assert passed["is_superuser"] is True


async def test_refresh_loads_token_with_row_lock():
    svc = AuthService.__new__(AuthService)
    svc.db = MagicMock()
    svc.db.commit = AsyncMock()
    svc.refresh_repo = AsyncMock()
    svc.user_repo = AsyncMock()
    revoked = MagicMock(revoked_at=object(), family_id="family")
    svc.refresh_repo.get_by_hash.return_value = revoked

    with pytest.raises(InvalidCredentialsException):
        await svc.refresh_access_token("refresh-token")

    svc.refresh_repo.get_by_hash.assert_awaited_once_with(
        hash_refresh_token("refresh-token"), for_update=True
    )
    svc.refresh_repo.revoke_family.assert_awaited_once_with("family")


async def test_authenticate_missing_user_still_verifies_dummy_hash(monkeypatch):
    svc = _make_auth_service(monkeypatch)
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
