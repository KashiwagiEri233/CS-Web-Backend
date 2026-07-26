"""RBAC service 层单元测试（不依赖数据库）。

用 AsyncMock 替换 RBACRepository，验证 update_role / update_permission /
get_user_roles / check_permission 的行为契约。
缓存被替换为每测独立的 no-op stub，避免全局内存缓存跨测试污染。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.rbac_service as rbac_svc_module
from app.core.exceptions import PermissionDeniedException
from app.services.rbac_seed_data import ADMIN_ROLE_NAME
from app.services.rbac_service import RBACService


def _stub_cache() -> MagicMock:
    """返回 no-op 缓存：get 恒未命中，set/delete 静默成功。"""
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=None)
    cache.delete = AsyncMock(return_value=None)
    return cache


def _make_service(monkeypatch) -> RBACService:
    """构造一个 repo 被 AsyncMock 替换、缓存被 no-op 替换的 RBACService。"""
    monkeypatch.setattr(rbac_svc_module, "get_cache", _stub_cache)
    svc = RBACService(db=MagicMock())
    svc.db = MagicMock()
    svc.db.commit = AsyncMock()  # service 内部会 await db.commit()
    svc.rbac_repo = AsyncMock()
    return svc


async def test_update_role_returns_none_when_missing(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.rbac_repo.get_role_by_id.return_value = None

    result = await svc.update_role(999, {"name": "x"})

    assert result is None
    svc.rbac_repo.update_role.assert_not_called()


async def test_update_role_delegates_to_repo(monkeypatch):
    svc = _make_service(monkeypatch)
    role = MagicMock(id=1)
    svc.rbac_repo.get_role_by_id.return_value = role
    svc.rbac_repo.get_role_by_name.return_value = None
    updated = MagicMock(id=1)
    svc.rbac_repo.update_role.return_value = updated

    result = await svc.update_role(1, {"name": "admin", "is_active": False})

    assert result is updated
    # 仅传入非 None 字段
    svc.rbac_repo.update_role.assert_awaited_once_with(
        role, {"name": "admin", "is_active": False}
    )


async def test_update_permission_returns_none_when_missing(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.rbac_repo.get_permission_by_id.return_value = None

    result = await svc.update_permission(999, {"name": "x"})

    assert result is None
    svc.rbac_repo.update_permission.assert_not_called()


async def test_update_permission_delegates_to_repo(monkeypatch):
    svc = _make_service(monkeypatch)
    perm = MagicMock(id=2)
    svc.rbac_repo.get_permission_by_id.return_value = perm
    svc.rbac_repo.get_permission_by_name.return_value = None
    svc.rbac_repo.get_permission_by_resource_and_action.return_value = None
    updated = MagicMock(id=2)
    svc.rbac_repo.update_permission.return_value = updated

    result = await svc.update_permission(2, {"resource": "user", "action": "read"})

    assert result is updated
    svc.rbac_repo.update_permission.assert_awaited_once_with(
        perm, {"resource": "user", "action": "read"}
    )


async def test_get_user_roles_empty_when_user_missing(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.rbac_repo.get_user_with_roles.return_value = None

    roles = await svc.get_user_roles(123)

    assert roles == []


async def test_get_user_roles_returns_user_roles(monkeypatch):
    svc = _make_service(monkeypatch)
    user = MagicMock()
    r1, r2 = MagicMock(name="r1"), MagicMock(name="r2")
    user.roles = [r1, r2]
    svc.rbac_repo.get_user_with_roles.return_value = user

    roles = await svc.get_user_roles(1)

    assert roles == [r1, r2]


async def test_check_permission_user_missing_returns_false(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.rbac_repo.get_user_with_roles.return_value = None

    assert await svc.check_permission(1, "x", "y") is False


async def test_check_permission_superuser_short_circuits(monkeypatch):
    svc = _make_service(monkeypatch)
    user = MagicMock()
    user.is_superuser = True
    svc.rbac_repo.get_user_with_roles.return_value = user

    # 超级用户即使无任何角色也应放行
    assert await svc.check_permission(1, "anything", "go") is True


async def test_check_permission_aggregates_roles(monkeypatch):
    svc = _make_service(monkeypatch)
    user = MagicMock()
    user.is_superuser = False

    p_hit = MagicMock(resource="user", action="read")
    p_miss = MagicMock(resource="user", action="delete")
    role = MagicMock()
    role.permissions = [p_hit, p_miss]
    user.roles = [role]
    svc.rbac_repo.get_user_with_roles.return_value = user

    assert await svc.check_permission(1, "user", "read") is True
    assert await svc.check_permission(1, "user", "delete") is True
    assert await svc.check_permission(1, "user", "write") is False


async def test_inactive_role_does_not_grant_permissions(monkeypatch):
    svc = _make_service(monkeypatch)
    user = MagicMock(is_superuser=False)
    permission = MagicMock(resource="user", action="delete")
    role = MagicMock(is_active=False, permissions=[permission])
    user.roles = [role]
    svc.rbac_repo.get_user_with_roles.return_value = user

    assert await svc.check_permission(1, "user", "delete") is False
    assert await svc.get_user_permissions(1) == set()


# ---- 角色/权限 CRUD 委托（路由层应通过这些方法访问数据） ----


async def test_get_all_roles_delegates(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.rbac_repo.get_all_roles.return_value = ["r1", "r2"]
    assert await svc.get_all_roles() == ["r1", "r2"]
    svc.rbac_repo.get_all_roles.assert_awaited_once()


async def test_get_role_delegates_to_get_role_with_permissions(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.rbac_repo.get_role_with_permissions.return_value = None
    assert await svc.get_role(9) is None
    svc.rbac_repo.get_role_with_permissions.assert_awaited_once_with(9)


async def test_create_role_delegates(monkeypatch):
    svc = _make_service(monkeypatch)
    payload = {"name": "x", "description": None, "is_active": True}
    svc.rbac_repo.create_role.return_value = "created"
    assert await svc.create_role(payload) == "created"
    svc.rbac_repo.create_role.assert_awaited_once_with(payload)


async def test_delete_role_delegates(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.rbac_repo.delete_role.return_value = True
    assert await svc.delete_role(3) is True
    svc.rbac_repo.delete_role.assert_awaited_once_with(3)


async def test_get_all_permissions_delegates(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.rbac_repo.get_all_permissions.return_value = ["p1"]
    assert await svc.get_all_permissions() == ["p1"]


async def test_get_permission_delegates_to_get_permission_by_id(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.rbac_repo.get_permission_by_id.return_value = None
    assert await svc.get_permission(5) is None
    svc.rbac_repo.get_permission_by_id.assert_awaited_once_with(5)


async def test_create_permission_delegates(monkeypatch):
    svc = _make_service(monkeypatch)
    payload = {"name": "p", "resource": "u", "action": "r", "description": None}
    svc.rbac_repo.create_permission.return_value = "created"
    assert await svc.create_permission(payload) == "created"
    svc.rbac_repo.create_permission.assert_awaited_once_with(payload)


async def test_delete_permission_delegates(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.rbac_repo.delete_permission.return_value = False
    assert await svc.delete_permission(7) is False


async def test_get_role_by_name_delegates(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.rbac_repo.get_role_by_name.return_value = None
    assert await svc.get_role_by_name("admin") is None


async def test_get_permission_by_name_delegates(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.rbac_repo.get_permission_by_name.return_value = "exists"
    assert await svc.get_permission_by_name("x") == "exists"


async def test_user_exists_true(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.rbac_repo.get_user_by_id.return_value = MagicMock()
    assert await svc.user_exists(1) is True


async def test_user_exists_false(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.rbac_repo.get_user_by_id.return_value = None
    assert await svc.user_exists(1) is False


# ---- grant/revoke 改用按 id 比较（#14） ----


async def test_grant_role_to_user_idempotent(monkeypatch):
    svc = _make_service(monkeypatch)
    user = MagicMock()
    existing = MagicMock(id=2)
    user.roles = [existing]
    svc.rbac_repo.get_user_with_roles.return_value = user
    svc.rbac_repo.get_role_by_id.return_value = existing  # 已存在同 id

    assert await svc.grant_role_to_user(1, 2) is True
    svc.db.commit.assert_not_called()  # 已有则不重复 append、不 commit


async def test_revoke_role_to_user_by_id(monkeypatch):
    svc = _make_service(monkeypatch)
    user = MagicMock()
    target = MagicMock(id=5)
    user.roles = [target]
    svc.rbac_repo.get_user_with_roles.return_value = user
    svc.rbac_repo.get_role_by_id.return_value = target

    assert await svc.revoke_role_from_user(1, 5) is True
    assert target not in user.roles


# ---- 权限缓存（#12） ----


def _real_memory_cache():
    """用项目自带的内存后端构造一个隔离缓存，验证命中/失效。

    这里用真实的 DegradableCache（不接 Redis），而不是 MagicMock 逐方法打桩：
    后者一旦生产代码新增缓存方法（如批量失效用的 delete_many），假对象会返回一个
    MagicMock，await 时抛 TypeError 又被失效逻辑的 except 吞掉——于是"缓存没被清"
    这种安全相关的回归会静默通过测试。用真对象则新方法天然可用。
    """
    from app.core.cache.backends import InMemoryCacheBackend
    from app.core.cache.cache import DegradableCache

    return DegradableCache(None, InMemoryCacheBackend())


async def test_get_user_permissions_caches_result(monkeypatch):
    """第二次调用应命中缓存，不再查库。"""
    cache = _real_memory_cache()
    monkeypatch.setattr(rbac_svc_module, "get_cache", lambda: cache)

    svc = RBACService.__new__(RBACService)
    svc.db = MagicMock()
    svc.rbac_repo = AsyncMock()

    user = MagicMock()
    perm = MagicMock(resource="user", action="read")
    role = MagicMock()
    role.permissions = [perm]
    user.roles = [role]
    svc.rbac_repo.get_user_with_roles.return_value = user

    first = await svc.get_user_permissions(1)
    second = await svc.get_user_permissions(1)

    assert first == {"user:read"}
    assert second == {"user:read"}
    # 命中缓存：底层只查了一次库
    assert svc.rbac_repo.get_user_with_roles.await_count == 1


async def test_grant_role_to_user_invalidates_cache(monkeypatch):
    """授予角色后应清除该用户权限缓存。"""
    cache = _real_memory_cache()
    await cache.set(rbac_svc_module._user_perm_cache_key(1), ["old"], 60)
    monkeypatch.setattr(rbac_svc_module, "get_cache", lambda: cache)

    svc = RBACService.__new__(RBACService)
    svc.db = MagicMock()
    svc.db.commit = AsyncMock()
    svc.rbac_repo = AsyncMock()

    user = MagicMock()
    user.roles = []
    role = MagicMock(id=7)
    svc.rbac_repo.get_user_with_roles.return_value = user
    svc.rbac_repo.get_role_by_id.return_value = role

    await svc.grant_role_to_user(1, 7)

    # 缓存已被失效
    assert await cache.get(rbac_svc_module._user_perm_cache_key(1)) is None


async def test_grant_permission_to_role_invalidates_all_role_users(monkeypatch):
    """角色授予权限应失效该角色下所有用户的权限缓存。"""
    cache = _real_memory_cache()
    # 用户 1 和 2 都在该角色下，预先写入缓存
    await cache.set(rbac_svc_module._user_perm_cache_key(1), ["x"], 60)
    await cache.set(rbac_svc_module._user_perm_cache_key(2), ["y"], 60)

    monkeypatch.setattr(rbac_svc_module, "get_cache", lambda: cache)

    svc = RBACService.__new__(RBACService)
    svc.db = MagicMock()
    svc.db.commit = AsyncMock()
    svc.rbac_repo = AsyncMock()

    role = MagicMock(id=3)
    role.permissions = []
    perm = MagicMock(id=4)
    svc.rbac_repo.get_role_with_permissions.return_value = role
    svc.rbac_repo.get_permission_by_id.return_value = perm
    svc.rbac_repo.get_user_ids_by_role.return_value = [1, 2]

    await svc.grant_permission_to_role(3, 4)

    assert await cache.get(rbac_svc_module._user_perm_cache_key(1)) is None
    assert await cache.get(rbac_svc_module._user_perm_cache_key(2)) is None


# ---- 提权防护：admin 角色 / 超级用户目标（actor 必须是超级用户） ----


def _make_actor(is_superuser: bool) -> MagicMock:
    return MagicMock(id=100, is_superuser=is_superuser)


def _make_role(role_id: int, name: str) -> MagicMock:
    role = MagicMock(id=role_id)
    role.name = name
    return role


async def test_grant_admin_role_requires_superuser(monkeypatch):
    svc = _make_service(monkeypatch)
    user = MagicMock(id=1, is_superuser=False)
    user.roles = []
    svc.rbac_repo.get_user_with_roles.return_value = user
    svc.rbac_repo.get_role_by_id.return_value = _make_role(9, ADMIN_ROLE_NAME)

    with pytest.raises(PermissionDeniedException):
        await svc.grant_role_to_user(1, 9, actor=_make_actor(False))

    svc.db.commit.assert_not_called()


async def test_grant_admin_role_allowed_for_superuser(monkeypatch):
    svc = _make_service(monkeypatch)
    user = MagicMock(id=1, is_superuser=False)
    user.roles = []
    svc.rbac_repo.get_user_with_roles.return_value = user
    svc.rbac_repo.get_role_by_id.return_value = _make_role(9, ADMIN_ROLE_NAME)

    assert await svc.grant_role_to_user(1, 9, actor=_make_actor(True)) is True


async def test_grant_role_to_superuser_target_requires_superuser(monkeypatch):
    svc = _make_service(monkeypatch)
    target = MagicMock(id=2, is_superuser=True)
    target.roles = []
    svc.rbac_repo.get_user_with_roles.return_value = target
    svc.rbac_repo.get_role_by_id.return_value = _make_role(3, "developer")

    with pytest.raises(PermissionDeniedException):
        await svc.grant_role_to_user(2, 3, actor=_make_actor(False))


async def test_revoke_role_from_superuser_target_requires_superuser(monkeypatch):
    svc = _make_service(monkeypatch)
    role = _make_role(3, "developer")
    target = MagicMock(id=2, is_superuser=True)
    target.roles = [role]
    svc.rbac_repo.get_user_with_roles.return_value = target
    svc.rbac_repo.get_role_by_id.return_value = role

    with pytest.raises(PermissionDeniedException):
        await svc.revoke_role_from_user(2, 3, actor=_make_actor(False))


async def test_grant_admin_role_without_actor_is_trusted_internal_call(monkeypatch):
    """actor=None（种子初始化/脚本）不受防护限制。"""
    svc = _make_service(monkeypatch)
    user = MagicMock(id=1, is_superuser=False)
    user.roles = []
    svc.rbac_repo.get_user_with_roles.return_value = user
    svc.rbac_repo.get_role_by_id.return_value = _make_role(9, ADMIN_ROLE_NAME)

    assert await svc.grant_role_to_user(1, 9) is True
