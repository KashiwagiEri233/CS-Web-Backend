"""UserService 单元测试（不依赖真实数据库）。

覆盖 list/get/update（含邮箱查重、密码哈希、自助不可改 is_active）/delete（自删拦截）。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ConflictException, NotFoundException
from app.services.user_service import UserService


def _make_service(monkeypatch) -> UserService:
    """构造 user_repo 被 AsyncMock 替换的 UserService。"""
    monkeypatch.setattr(
        "app.services.user_service.get_password_hash", lambda raw: f"hash:{raw}"
    )
    svc = UserService.__new__(UserService)
    svc.db = MagicMock()
    svc.user_repo = AsyncMock()
    return svc


# ---- list / get ----

async def test_list_users_returns_users_and_total(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.user_repo.get_all.return_value = ["u1", "u2"]
    svc.user_repo.count.return_value = 2

    users, total = await svc.list_users(skip=0, limit=10)

    assert users == ["u1", "u2"]
    assert total == 2


async def test_get_user_raises_when_missing(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.user_repo.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await svc.get_user(9)


async def test_get_user_returns_user(monkeypatch):
    svc = _make_service(monkeypatch)
    u = MagicMock(id=1)
    svc.user_repo.get_by_id.return_value = u

    assert await svc.get_user(1) is u


# ---- update_user ----

async def test_update_user_applies_fields_and_hashes_password(monkeypatch):
    svc = _make_service(monkeypatch)
    user = MagicMock(id=3, email="old@t.com", full_name="old", hashed_password="h")
    svc.user_repo.get_by_id.return_value = user
    svc.user_repo.get_by_email.return_value = None
    svc.user_repo.update.return_value = user

    result = await svc.update_user(3, {
        "email": "new@t.com", "full_name": "nn", "password": "secret", "is_active": False
    })

    assert result is user
    assert user.email == "new@t.com"
    assert user.full_name == "nn"
    assert user.hashed_password == "hash:secret"
    assert user.is_active is False


async def test_update_user_blocks_conflicting_email(monkeypatch):
    svc = _make_service(monkeypatch)
    user = MagicMock(id=3, email="old@t.com", full_name=None, hashed_password="h", is_active=True)
    svc.user_repo.get_by_id.return_value = user
    # 他人占用邮箱
    other = MagicMock(id=99)
    svc.user_repo.get_by_email.return_value = other

    with pytest.raises(ConflictException):
        await svc.update_user(3, {"email": "taken@t.com"})


async def test_update_user_allows_same_email(monkeypatch):
    """更新为本人当前邮箱不应判冲突。"""
    svc = _make_service(monkeypatch)
    user = MagicMock(id=3, email="same@t.com", full_name=None, hashed_password="h", is_active=True)
    svc.user_repo.get_by_id.return_value = user
    svc.user_repo.get_by_email.return_value = user  # 查到的是自己

    await svc.update_user(3, {"email": "same@t.com"})
    assert user.email == "same@t.com"


# ---- update_profile（自助：不可改 is_active） ----

async def test_update_profile_ignores_is_active(monkeypatch):
    svc = _make_service(monkeypatch)
    user = MagicMock(id=3, email="e@t.com", full_name=None, hashed_password="h", is_active=True)
    svc.user_repo.get_by_email.return_value = None
    svc.user_repo.update.return_value = user

    await svc.update_profile(user, {"full_name": "x", "is_active": False})

    assert user.full_name == "x"
    # is_active 被忽略，保持原值
    assert user.is_active is True


async def test_update_profile_allows_password_change(monkeypatch):
    svc = _make_service(monkeypatch)
    user = MagicMock(id=3, email="e@t.com", full_name=None, hashed_password="h", is_active=True)
    svc.user_repo.get_by_email.return_value = None
    svc.user_repo.update.return_value = user

    await svc.update_profile(user, {"password": "newp"})

    assert user.hashed_password == "hash:newp"


# ---- delete_user ----

async def test_delete_user_prevents_self_delete(monkeypatch):
    svc = _make_service(monkeypatch)

    with pytest.raises(ConflictException):
        await svc.delete_user(5, current_user_id=5)


async def test_delete_user_raises_when_missing(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.user_repo.delete.return_value = False

    with pytest.raises(NotFoundException):
        await svc.delete_user(9, current_user_id=1)


async def test_delete_user_succeeds(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.user_repo.delete.return_value = True

    await svc.delete_user(9, current_user_id=1)
    svc.user_repo.delete.assert_awaited_once_with(9)
