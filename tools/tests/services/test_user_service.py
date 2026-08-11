"""UserService 单元测试（不依赖真实数据库）。

覆盖 list/get/update（含邮箱查重、密码哈希、自助不可改 is_active）/delete（自删拦截）。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import (
    ConflictException,
    InvalidCredentialsException,
    NotFoundException,
    PermissionDeniedException,
    ValidationException,
)
from app.services.user_service import UserService


@pytest.fixture
def user_service(monkeypatch) -> UserService:
    """注入 mock db 的真实 UserService（ER-41：不再绕 __init__）。

    行为层（user_repo / refresh_repo）仍用 AsyncMock 替换，避免真实 SQL；
    __init__ 正常执行，新增依赖初始化会在此暴露。
    """
    monkeypatch.setattr(
        "app.services.user_service.async_get_password_hash",
        AsyncMock(side_effect=lambda raw: f"hash:{raw}"),
    )
    db = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    svc = UserService(db=db)
    svc.user_repo = AsyncMock()
    svc.refresh_repo = AsyncMock()
    svc.refresh_repo.revoke_all_for_user = AsyncMock(return_value=0)
    return svc


# ---- list / get ----


async def test_list_users_returns_users_and_total(user_service, monkeypatch):
    svc = user_service
    svc.user_repo.list_active.return_value = ["u1", "u2"]
    svc.user_repo.count_active.return_value = 2

    users, total = await svc.list_users(skip=0, limit=10)

    assert users == ["u1", "u2"]
    assert total == 2
    svc.user_repo.list_active.assert_awaited_once_with(skip=0, limit=10)
    svc.user_repo.count_active.assert_awaited_once_with()


async def test_get_user_raises_when_missing(user_service, monkeypatch):
    svc = user_service
    svc.user_repo.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await svc.get_user(9)


async def test_get_user_returns_user(user_service, monkeypatch):
    svc = user_service
    u = MagicMock(id=1, deleted_at=None)
    svc.user_repo.get_by_id.return_value = u

    assert await svc.get_user(1) is u


# ---- update_user ----


async def test_update_user_applies_fields_and_hashes_password(user_service, monkeypatch):
    svc = user_service
    user = MagicMock(
        id=3, email="old@t.com", full_name="old", hashed_password="h", deleted_at=None
    )
    svc.user_repo.get_by_id.return_value = user
    svc.user_repo.get_by_email.return_value = None
    svc.user_repo.update.return_value = user

    result = await svc.update_user(
        3,
        {
            "email": "new@t.com",
            "full_name": "nn",
            "password": "secret",
            "is_active": False,
        },
    )

    assert result is user
    assert user.email == "new@t.com"
    assert user.full_name == "nn"
    assert user.hashed_password == "hash:secret"
    assert user.is_active is False
    assert user.password_changed_at is not None
    svc.refresh_repo.revoke_all_for_user.assert_awaited_with(3)
    svc.db.commit.assert_awaited()


async def test_update_user_blocks_conflicting_email(user_service, monkeypatch):
    svc = user_service
    user = MagicMock(
        id=3,
        deleted_at=None,
        email="old@t.com",
        full_name=None,
        hashed_password="h",
        is_active=True,
    )
    svc.user_repo.get_by_id.return_value = user
    # 他人占用邮箱（未软删）
    other = MagicMock(id=99, deleted_at=None)
    svc.user_repo.get_by_email.return_value = other

    with pytest.raises(ConflictException):
        await svc.update_user(3, {"email": "taken@t.com"})


async def test_update_user_allows_same_email(user_service, monkeypatch):
    """更新为本人当前邮箱不应判冲突。"""
    svc = user_service
    user = MagicMock(
        id=3,
        deleted_at=None,
        email="same@t.com",
        full_name=None,
        hashed_password="h",
        is_active=True,
    )
    svc.user_repo.get_by_id.return_value = user
    svc.user_repo.get_by_email.return_value = user  # 查到的是自己

    await svc.update_user(3, {"email": "same@t.com"})
    assert user.email == "same@t.com"


# ---- update_profile（自助：不可改 is_active） ----


async def test_update_profile_ignores_is_active(user_service, monkeypatch):
    svc = user_service
    user = MagicMock(
        id=3,
        deleted_at=None,
        email="e@t.com",
        full_name=None,
        hashed_password="h",
        is_active=True,
    )
    svc.user_repo.get_by_email.return_value = None
    svc.user_repo.update.return_value = user

    await svc.update_profile(user, {"full_name": "x", "is_active": False})

    assert user.full_name == "x"
    # is_active 被忽略，保持原值
    assert user.is_active is True


async def test_update_profile_allows_password_change(user_service, monkeypatch):
    svc = user_service
    monkeypatch.setattr(
        "app.services.user_service.async_verify_password",
        AsyncMock(return_value=True),
    )
    user = MagicMock(
        id=3,
        deleted_at=None,
        email="e@t.com",
        full_name=None,
        hashed_password="h",
        is_active=True,
    )
    svc.user_repo.get_by_email.return_value = None
    svc.user_repo.update.return_value = user

    await svc.update_profile(user, {"password": "newp", "old_password": "oldp"})

    assert user.hashed_password == "hash:newp"


async def test_update_profile_password_requires_old_password(user_service, monkeypatch):
    """自助改密必须提供当前密码，缺失则 422。"""
    svc = user_service
    user = MagicMock(id=3, hashed_password="h")

    with pytest.raises(ValidationException):
        await svc.update_profile(user, {"password": "newp"})

    svc.user_repo.update.assert_not_called()


async def test_update_profile_rejects_wrong_old_password(user_service, monkeypatch):
    """旧密码错误拒绝改密，且不会进入字段更新流程。"""
    svc = user_service
    verify = AsyncMock(return_value=False)
    monkeypatch.setattr("app.services.user_service.async_verify_password", verify)
    user = MagicMock(id=3, hashed_password="h")

    with pytest.raises(InvalidCredentialsException):
        await svc.update_profile(user, {"password": "newp", "old_password": "bad"})

    verify.assert_awaited_once_with("bad", "h")
    svc.user_repo.update.assert_not_called()


# ---- delete_user ----


def _actor(user_id: int = 1, is_superuser: bool = False) -> MagicMock:
    return MagicMock(id=user_id, is_superuser=is_superuser)


async def test_delete_user_prevents_self_delete(user_service, monkeypatch):
    svc = user_service

    with pytest.raises(ConflictException):
        await svc.delete_user(5, actor=_actor(user_id=5))


async def test_delete_user_raises_when_missing(user_service, monkeypatch):
    svc = user_service
    svc.user_repo.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await svc.delete_user(9, actor=_actor())


async def test_delete_user_succeeds(user_service, monkeypatch):
    svc = user_service
    user = MagicMock(
        id=9,
        deleted_at=None,
        username="victim",
        email="v@t.com",
        is_active=True,
        is_superuser=False,
    )
    svc.user_repo.get_by_id.return_value = user
    svc.user_repo.update.return_value = user

    await svc.delete_user(9, actor=_actor())
    assert user.deleted_at is not None
    assert user.is_active is False
    svc.refresh_repo.revoke_all_for_user.assert_awaited_with(9)
    svc.db.commit.assert_awaited()


# ---- 超级用户操纵防护 ----


async def test_update_user_blocks_non_superuser_editing_superuser(user_service, monkeypatch):
    """非超管 actor 更新超管账号 → 拒绝（防提权接管）。"""
    svc = user_service
    target = MagicMock(id=3, deleted_at=None, is_superuser=True)
    svc.user_repo.get_by_id.return_value = target

    with pytest.raises(PermissionDeniedException):
        await svc.update_user(3, {"is_active": False}, actor=_actor())

    svc.user_repo.update.assert_not_called()


async def test_update_user_allows_superuser_editing_superuser(user_service, monkeypatch):
    """超管 actor 更新超管账号 → 放行。"""
    svc = user_service
    target = MagicMock(
        id=3,
        deleted_at=None,
        is_superuser=True,
        email="a@t.com",
        full_name=None,
        hashed_password="h",
        is_active=True,
    )
    svc.user_repo.get_by_id.return_value = target
    svc.user_repo.get_by_email.return_value = None
    svc.user_repo.update.return_value = target

    await svc.update_user(3, {"full_name": "x"}, actor=_actor(is_superuser=True))
    assert target.full_name == "x"


async def test_delete_user_blocks_non_superuser_deleting_superuser(user_service, monkeypatch):
    """非超管 actor 删除超管账号 → 拒绝。"""
    svc = user_service
    target = MagicMock(id=9, deleted_at=None, is_superuser=True)
    svc.user_repo.get_by_id.return_value = target

    with pytest.raises(PermissionDeniedException):
        await svc.delete_user(9, actor=_actor())

    svc.user_repo.update.assert_not_called()
