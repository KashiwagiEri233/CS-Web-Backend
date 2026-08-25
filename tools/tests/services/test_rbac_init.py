"""RBAC seed 的安全与收敛行为测试。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.rbac.rbac_init as rbac_init_module
from app.services.rbac.rbac_init import RBACInitializer


def _initializer() -> RBACInitializer:
    db = MagicMock()
    db.flush = AsyncMock()
    db.rollback = AsyncMock()
    initializer = RBACInitializer(db)
    initializer.user_repo = AsyncMock()
    initializer.rbac_repo = AsyncMock()
    return initializer


async def test_first_admin_requires_explicit_password():
    initializer = _initializer()
    initializer.user_repo.get_by_username.return_value = None
    admin_role = MagicMock(name="admin-role")
    admin_role.name = "admin"

    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        await initializer._create_admin_user(
            "admin", "admin@example.com", None, [admin_role]
        )

    initializer.db.add.assert_not_called()


async def test_existing_admin_does_not_require_password():
    initializer = _initializer()
    initializer.user_repo.get_by_username.return_value = MagicMock()

    assert not await initializer._create_admin_user(
        "admin", "admin@example.com", None, []
    )


async def test_existing_default_role_gets_new_permission_without_removing_custom(
    monkeypatch,
):
    initializer = _initializer()
    existing_permission = MagicMock(resource="user", action="read")
    new_permission = MagicMock(resource="user", action="list")
    custom_permission = MagicMock(resource="custom", action="keep")
    role = MagicMock(id=7, permissions=[existing_permission, custom_permission])

    monkeypatch.setattr(
        rbac_init_module,
        "build_default_roles",
        lambda _keys: [
            {
                "name": "developer",
                "description": "dev",
                "permissions": ["user:read", "user:list"],
            }
        ],
    )
    initializer.rbac_repo.get_role_by_name.return_value = MagicMock(id=7)
    initializer.rbac_repo.get_role_with_permissions.return_value = role

    roles, created = await initializer._create_default_roles(
        [existing_permission, new_permission]
    )

    assert created == 0
    assert roles == [role]
    assert role.permissions == [existing_permission, custom_permission, new_permission]
