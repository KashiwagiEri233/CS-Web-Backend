"""权限校验依赖（PermissionChecker / require_permission）测试。

直接测试依赖的 __call__ 逻辑，monkeypatch 掉权限查询，不依赖数据库。
"""

import pytest

from app.middleware.rbac import PermissionChecker, require_permission
from app.core.exceptions import PermissionDeniedException
import app.middleware.rbac as rbac_module


class _FakeUser:
    def __init__(self, user_id=1, is_superuser=False):
        self.id = user_id
        self.is_superuser = is_superuser


def _patch_permissions(monkeypatch, perms):
    async def fake_get_user_permissions(self, user_id):
        return set(perms)
    monkeypatch.setattr(
        rbac_module.RBACService, "get_user_permissions", fake_get_user_permissions
    )


async def test_superuser_bypasses_permission_check(monkeypatch):
    # 即使没有任何权限，超级用户也放行
    _patch_permissions(monkeypatch, set())
    checker = require_permission("exception", "read")
    user = _FakeUser(is_superuser=True)
    result = await checker(current_user=user, db=None)
    assert result is user


async def test_user_with_permission_is_allowed(monkeypatch):
    _patch_permissions(monkeypatch, {"exception:read"})
    checker = require_permission("exception", "read")
    user = _FakeUser(is_superuser=False)
    result = await checker(current_user=user, db=None)
    assert result is user


async def test_user_without_permission_is_denied(monkeypatch):
    _patch_permissions(monkeypatch, {"other:read"})
    checker = require_permission("exception", "read")
    user = _FakeUser(is_superuser=False)
    with pytest.raises(PermissionDeniedException):
        await checker(current_user=user, db=None)


async def test_require_all_semantics(monkeypatch):
    _patch_permissions(monkeypatch, {"a:read"})
    user = _FakeUser(is_superuser=False)

    # require_all=True：缺一即拒
    all_checker = PermissionChecker(["a:read", "b:read"], require_all=True)
    with pytest.raises(PermissionDeniedException):
        await all_checker(current_user=user, db=None)

    # require_all=False：命中其一即放行
    any_checker = PermissionChecker(["a:read", "b:read"], require_all=False)
    assert await any_checker(current_user=user, db=None) is user
