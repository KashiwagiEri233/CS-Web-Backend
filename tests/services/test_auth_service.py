"""AuthService.create_user 单元测试（不依赖真实数据库）。

验证 #2 修复：用户创建逻辑统一入口——查重、哈希、full_name 写入、is_superuser 控制。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import UserAlreadyExistsException
from app.services.auth_service import AuthService


def _make_auth_service(monkeypatch) -> AuthService:
    """构造 user_repo 被 AsyncMock 替换的 AuthService。

    绕开 __init__（避免实例化 RefreshTokenRepository 等真实依赖）。
    create_user 内部局部 import get_password_hash，故 patch 其真实来源。
    """
    monkeypatch.setattr(
        "app.core.security.get_password_hash", lambda raw: f"hash:{raw}"
    )
    svc = AuthService.__new__(AuthService)
    svc.db = MagicMock()
    svc.db.commit = AsyncMock()  # service 层统一 commit
    svc.user_repo = AsyncMock()
    return svc


class _UserData:
    """模拟 schemas.auth.UserCreate 的最小形态。"""

    def __init__(self, username="u", email="e@t.com", password="secret",
                 full_name=None, is_active=True):
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
