"""P6 安全矩阵：角色绑定提权与租户/作用范围防越权（单元级）。

用 AsyncMock 替换 RBACRepository，覆盖：
- If-Match 缺失 428 / 失配 412；
- 非超级用户不得分配受保护角色、不得修改超级用户授权；
- 非超级用户不得委托含安全管理权限的自定义角色；
- 角色 scope 必须符合策略（member 只能 own，peak_manager 只能 peak）；
- peak 范围必须指定存在且有效的峰。

全部为纯内存断言，不连接真实数据库。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.rbac.rbac_service as rbac_svc_module
from app.core.exceptions import (
    AuthorizationException,
    BaseAppException,
    NotFoundException,
)
from app.services.rbac.rbac_service import RBACService


def _stub_cache() -> MagicMock:
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=None)
    cache.delete = AsyncMock(return_value=None)
    return cache


@pytest.fixture
def svc(monkeypatch) -> RBACService:
    monkeypatch.setattr(rbac_svc_module, "get_cache", _stub_cache)
    monkeypatch.setattr(
        rbac_svc_module, "_invalidate_user_perm_cache", AsyncMock(return_value=None)
    )
    service = RBACService(db=MagicMock())
    service.db = MagicMock()
    service.db.commit = AsyncMock()
    service.rbac_repo = AsyncMock()
    return service


def _actor(is_superuser: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=999, is_superuser=is_superuser, username="actor")


def _role(name: str, role_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(id=role_id, name=name)


async def _prepare_user(svc: RBACService, version: int = 3, is_superuser: bool = False):
    svc.rbac_repo.get_user_authorization_version.return_value = version
    svc.rbac_repo.get_user_with_roles.return_value = SimpleNamespace(
        id=10, is_superuser=is_superuser
    )
    svc.rbac_repo.get_user_bindings.return_value = []


async def test_missing_if_match_rejected_428(svc):
    await _prepare_user(svc)
    with pytest.raises(BaseAppException) as exc:
        await svc.replace_user_role_bindings(
            10, [], actor=_actor(), expected_version=None
        )
    assert exc.value.status_code == 428


async def test_version_mismatch_rejected_412(svc):
    await _prepare_user(svc, version=5)
    with pytest.raises(BaseAppException) as exc:
        await svc.replace_user_role_bindings(
            10, [], actor=_actor(), expected_version=4
        )
    assert exc.value.status_code == 412
    assert exc.value.details["current_version"] == 5


async def test_unknown_user_not_found(svc):
    svc.rbac_repo.get_user_authorization_version.return_value = None
    with pytest.raises(NotFoundException):
        await svc.replace_user_role_bindings(
            404, [], actor=_actor(), expected_version=1
        )


async def test_non_superuser_cannot_grant_protected_role(svc):
    await _prepare_user(svc)
    svc.rbac_repo.get_role_by_id.return_value = _role("admin")
    with pytest.raises(AuthorizationException):
        await svc.replace_user_role_bindings(
            10,
            [{"role_id": 1, "scope_type": "all", "scope_peak_id": None}],
            actor=_actor(is_superuser=False),
            expected_version=3,
        )


async def test_non_superuser_cannot_modify_superuser_target(svc):
    await _prepare_user(svc, is_superuser=True)
    svc.rbac_repo.get_role_by_id.return_value = _role("member")
    with pytest.raises(AuthorizationException):
        await svc.replace_user_role_bindings(
            10,
            [{"role_id": 2, "scope_type": "own", "scope_peak_id": None}],
            actor=_actor(is_superuser=False),
            expected_version=3,
        )


async def test_non_superuser_cannot_delegate_security_permissions(svc):
    await _prepare_user(svc)
    svc.rbac_repo.get_role_by_id.return_value = _role("custom_ops", role_id=77)
    svc.rbac_repo.get_role_permissions_names.return_value = {"role:manage_permissions"}
    with pytest.raises(AuthorizationException):
        await svc.replace_user_role_bindings(
            10,
            [{"role_id": 77, "scope_type": "own", "scope_peak_id": None}],
            actor=_actor(is_superuser=False),
            expected_version=3,
        )


async def test_member_role_only_allows_own_scope(svc):
    await _prepare_user(svc)
    svc.rbac_repo.get_role_by_id.return_value = _role("member")
    with pytest.raises(AuthorizationException):
        await svc.replace_user_role_bindings(
            10,
            [{"role_id": 2, "scope_type": "all", "scope_peak_id": None}],
            actor=_actor(is_superuser=True),
            expected_version=3,
        )


async def test_peak_scope_requires_existing_active_peak(svc):
    await _prepare_user(svc)
    svc.rbac_repo.get_role_by_id.return_value = _role("peak_manager")
    svc.rbac_repo.get_peak_by_id.return_value = SimpleNamespace(
        id=5, is_active=False, archived_at=None
    )
    with pytest.raises(AuthorizationException):
        await svc.replace_user_role_bindings(
            10,
            [{"role_id": 3, "scope_type": "peak", "scope_peak_id": 5}],
            actor=_actor(is_superuser=True),
            expected_version=3,
        )


async def test_peak_scope_requires_peak_id(svc):
    await _prepare_user(svc)
    svc.rbac_repo.get_role_by_id.return_value = _role("peak_manager")
    with pytest.raises(AuthorizationException):
        await svc.replace_user_role_bindings(
            10,
            [{"role_id": 3, "scope_type": "peak", "scope_peak_id": None}],
            actor=_actor(is_superuser=True),
            expected_version=3,
        )


async def test_non_peak_scope_cannot_carry_peak_id(svc):
    await _prepare_user(svc)
    svc.rbac_repo.get_role_by_id.return_value = _role("member")
    with pytest.raises(AuthorizationException):
        await svc.replace_user_role_bindings(
            10,
            [{"role_id": 2, "scope_type": "own", "scope_peak_id": 9}],
            actor=_actor(is_superuser=True),
            expected_version=3,
        )


async def test_duplicate_bindings_deduplicated(svc):
    await _prepare_user(svc)
    svc.rbac_repo.get_role_by_id.return_value = _role("member", role_id=2)
    svc.rbac_repo.replace_user_bindings.return_value = None

    await svc.replace_user_role_bindings(
        10,
        [
            {"role_id": 2, "scope_type": "own", "scope_peak_id": None},
            {"role_id": 2, "scope_type": "own", "scope_peak_id": None},
        ],
        actor=_actor(is_superuser=True),
        expected_version=3,
    )
    passed = svc.rbac_repo.replace_user_bindings.await_args.args[1]
    assert len(passed) == 1
