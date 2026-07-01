"""RBAC service 层单元测试（不依赖数据库）。

用 AsyncMock 替换 RBACRepository，验证 update_role / update_permission /
get_user_roles / check_permission 的行为契约。
"""

from unittest.mock import AsyncMock, MagicMock

from app.services.rbac_service import RBACService


def _make_service(monkeypatch) -> RBACService:
    """构造一个 repo 被 AsyncMock 替换的 RBACService。"""
    svc = RBACService(db=MagicMock())
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
    updated = MagicMock(id=1)
    svc.rbac_repo.update_role.return_value = updated

    result = await svc.update_role(1, {"name": "admin", "is_active": False})

    assert result is updated
    # 仅传入非 None 字段
    svc.rbac_repo.update_role.assert_awaited_once_with(role, {"name": "admin", "is_active": False})


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
