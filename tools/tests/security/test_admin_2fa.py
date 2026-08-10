"""P0 管理员强制 2FA：纯逻辑判定（无需 DB）。

覆盖 app.middleware.rbac 的 is_admin_role / enforce_admin_2fa：
- 管理员（admin 角色 / 超级用户）未启用 2FA → 拒绝
- 已启用 → 放行
- 非管理员 → 不受此闸门约束
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ErrorCode, ValidationException
from app.middleware.rbac import enforce_admin_2fa, is_admin_role


class _Role:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeUser:
    """鸭子类型模拟 User：仅需 is_superuser / roles。"""

    def __init__(self, is_superuser: bool = False, roles: list | None = None) -> None:
        self.is_superuser = is_superuser
        self.roles = roles or []


def test_is_admin_role_detection():
    assert is_admin_role(_FakeUser(is_superuser=True)) is True
    assert is_admin_role(_FakeUser(roles=[_Role("admin")])) is True
    assert is_admin_role(_FakeUser(roles=[_Role("member")])) is False
    assert is_admin_role(_FakeUser()) is False


def test_non_admin_passes_without_2fa():
    # 普通成员不受管理员 2FA 闸门约束
    enforce_admin_2fa(_FakeUser(roles=[_Role("member")]), twofa_enabled=False)


def test_admin_blocked_without_2fa():
    with pytest.raises(ValidationException) as exc:
        enforce_admin_2fa(_FakeUser(roles=[_Role("admin")]), twofa_enabled=False)
    assert exc.value.error_code == ErrorCode.Auth.TWO_FACTOR_NOT_SETUP


def test_superuser_blocked_without_2fa():
    with pytest.raises(ValidationException) as exc:
        enforce_admin_2fa(_FakeUser(is_superuser=True), twofa_enabled=False)
    assert exc.value.error_code == ErrorCode.Auth.TWO_FACTOR_NOT_SETUP


def test_admin_allowed_with_2fa():
    enforce_admin_2fa(_FakeUser(roles=[_Role("admin")]), twofa_enabled=True)
    enforce_admin_2fa(_FakeUser(is_superuser=True), twofa_enabled=True)
