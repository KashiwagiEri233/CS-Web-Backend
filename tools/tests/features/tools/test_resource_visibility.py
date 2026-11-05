"""资源可见性与管理员控制台权限（A03）单元测试（不依赖真实数据库）。

覆盖两类越权修复：
1. 公开资源列表固定 approved；详情按「已审核 / 本人 / 管理员」三态收敛。
2. 全站 API 用量端点必须「有权限 + 已启用 2FA」，不得只靠 Admin2FARequired
   （该依赖对非管理员 fail-open）。
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.middleware.rbac import Admin2FARequired, is_admin_role


def _user(uid: int = 1, *, is_superuser: bool = False, roles: list[str] | None = None):
    return SimpleNamespace(
        id=uid,
        is_superuser=is_superuser,
        roles=[SimpleNamespace(name=r) for r in (roles or [])],
    )


# ---- 1) Admin2FARequired 对非管理员 fail-open（这正是 A03 的成因）----


async def test_admin_2fa_fail_open_for_normal_user():
    """非管理员：依赖直接放行 —— 证明「只挂 2FA」不能当权限校验用。"""
    dep = Admin2FARequired()
    sentinel = _user(roles=["user"])

    # 绕过 DB/TOTP：非管理员分支在查库前就 return
    result = await dep(current_user=sentinel, db=MagicMock())

    assert result is sentinel


def test_is_admin_role_matrix():
    assert is_admin_role(_user(is_superuser=True)) is True
    assert is_admin_role(_user(roles=["admin"])) is True
    assert is_admin_role(_user(roles=["user"])) is False
    assert is_admin_role(_user(roles=["developer"])) is False


# ---- 2) 资源详情可见性三态 ----


def _resource(status: str, submitted_by: int = 1):
    """构造满足 ResourceOut 校验的完整资源（缺字段会触发 pydantic 校验失败）。"""
    return SimpleNamespace(
        id=10,
        title="示例资源",
        url="https://example.com/r",
        description=None,
        resource_type="article",
        tech_tags=[],
        status=status,
        submitted_by=submitted_by,
        submitted_by_name=None,
        reviewed_by=None,
        review_note=None,
        file_url=None,
        view_count=0,
        like_count=0,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


async def _can_view(resource, current_user) -> bool:
    """直接调用**真实路由函数**判定可见性（避免测试复刻逻辑而与实现漂移）。"""
    from app.api.v1.tools.resource import get_resource
    from app.core.exceptions import AuthorizationException

    service = MagicMock()
    service.get_resource = AsyncMock(return_value=resource)
    try:
        await get_resource(
            resource_id=resource.id,
            service=service,
            current_user=current_user,
        )
    except AuthorizationException:
        return False
    return True


@pytest.mark.parametrize(
    ("status", "user", "expected"),
    [
        ("approved", None, True),  # 匿名可读已审核
        ("pending", None, False),  # 匿名不可读待审
        ("rejected", None, False),  # 匿名不可读已驳回
        ("pending", _user(uid=1), True),  # 作者本人可预览
        ("pending", _user(uid=2), False),  # 他人不可读
        ("pending", _user(uid=2, is_superuser=True), True),  # 超级用户可预览
        ("pending", _user(uid=2, roles=["admin"]), True),  # admin 角色可预览
        ("rejected", _user(uid=2, roles=["developer"]), False),  # 非 admin 角色不可
    ],
)
async def test_resource_visibility_matrix(status, user, expected):
    assert await _can_view(_resource(status, submitted_by=1), user) is expected


# ---- 3) 公开列表固定 approved ----


async def test_public_list_forces_approved_status():
    """公开列表 MUST 固定 status=approved，不得透传 None（否则匿名可读待审内容）。"""
    from app.api.v1.tools.resource import list_resources

    service = MagicMock()
    service.list_resources = AsyncMock(return_value=([], 0))
    # PaginationParams 是 FastAPI 查询模型（直接实例化会拿到 Query 默认对象），
    # 这里用等价的最小桩替代，只提供路由读取的 skip/limit。
    pagination = SimpleNamespace(skip=0, limit=20)

    await list_resources(
        pagination=pagination,
        tag=None,
        service=service,
    )

    kwargs = service.list_resources.await_args.kwargs
    assert kwargs["status"] == "approved", "公开列表必须固定只出已审核资源"


# ---- 4) 权限种子：admin 独占 admin:console_read ----


def test_admin_console_read_granted_only_to_admin_role():
    """新增的 admin:console_read 必须由 admin 角色持有，且其他角色不得持有。"""
    from app.services.rbac.rbac_seed_data import (
        DEFAULT_PERMISSIONS,
        build_default_roles,
    )

    names = [p["name"] for p in DEFAULT_PERMISSIONS]
    assert "admin:console_read" in names, "权限种子必须包含 admin:console_read"

    all_keys = names
    roles = {r["name"]: set(r["permissions"]) for r in build_default_roles(all_keys)}

    assert "admin:console_read" in roles["admin"]

    # 非 admin 角色不得持有该控制台权限（防止过度放权）
    for role_name, perms in roles.items():
        if role_name == "admin":
            continue
        assert (
            "admin:console_read" not in perms
        ), f"角色 {role_name} 不应持有 admin:console_read"
