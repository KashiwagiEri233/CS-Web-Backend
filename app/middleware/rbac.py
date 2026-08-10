"""RBAC 权限校验依赖。

设计为 FastAPI 依赖（Depends），而非函数装饰器：
- 装饰器方案依赖 `kwargs.get("current_user")` 反射取参，脆弱且不可组合；
- 依赖方案天然参与 FastAPI 的依赖解析与缓存，可放进路由 `dependencies=[...]`，
  也可作为参数注入（校验通过返回当前用户）。

用法：
    from app.middleware.rbac import require_permission

    @router.get("/x", dependencies=[Depends(require_permission("user", "read"))])
    async def x(): ...

    # 或需要在函数体内使用当前用户时：
    async def y(user: User = Depends(require_permission("user", "read"))): ...
"""

from typing import List, Union

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ErrorCode, PermissionDeniedException, ValidationException
from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.user import User
from app.services.rbac_service import RBACService
from app.services.totp_service import TOTPService


class PermissionChecker:
    """权限校验依赖：校验当前用户是否具备所需权限。"""

    def __init__(
        self, required_permissions: Union[str, List[str]], require_all: bool = True
    ):
        if isinstance(required_permissions, str):
            required_permissions = [required_permissions]
        self.required_permissions = required_permissions
        self.require_all = require_all

    async def __call__(
        self,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        # 超级用户拥有所有权限
        if current_user.is_superuser:
            return current_user

        # 授权判定走带 TTL 缓存的权限集：所有变更点（grant/revoke/update/delete）
        # 都做了显式失效，撤权延迟已被主动失效覆盖；缓存故障时自动回退查库。
        # 相比每请求直查库（user+roles+permissions 三条 SQL），这是高并发下
        # 数据库负载的最大单一来源。
        rbac_service = RBACService(db)
        permissions = await rbac_service.get_user_permissions(current_user.id)
        checks = [
            ":" in permission and permission in permissions
            for permission in self.required_permissions
        ]

        ok = all(checks) if self.require_all else any(checks)

        if not ok:
            raise PermissionDeniedException(
                required_permissions=self.required_permissions
            )
        return current_user


def require_permission(
    resource: str, action: str, require_all: bool = True
) -> PermissionChecker:
    """构造权限校验依赖：require_permission("user", "read") -> Depends 可用对象。"""
    return PermissionChecker(f"{resource}:{action}", require_all)


# ------------------------------------------------------------------ 管理员强制 2FA


def is_admin_role(user: User) -> bool:
    """管理员 = 超级用户 或 持有 admin 角色。

    提取为纯函数便于单测，不直接依赖 DB。
    """
    return user.is_superuser or any(r.name == "admin" for r in user.roles)


class Admin2FARequired:
    """管理员高危面强制 2FA（P0：管理员强制 2FA）。

    已通过 ``require_permission`` 鉴权的管理员/超级用户，必须已启用 TOTP，
    否则拒绝访问管理后台（未启用即拒，杜绝「未启用直接放行」绕过）。
    判定与 ``feature_visibility`` 的 root 2FA 强制（决策点 B）同源。
    """

    async def __call__(
        self,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        # 非管理员直接放行（普通成员不会进入 admin 端点，此处为防御性短路）。
        if not is_admin_role(current_user):
            return current_user
        totp = TOTPService(db)
        if not await totp.is_enabled(current_user.id):
            raise ValidationException(
                message="管理员必须先启用两步验证（2FA）才能访问管理后台",
                error_code=ErrorCode.Auth.TWO_FACTOR_NOT_SETUP,
            )
        return current_user


def enforce_admin_2fa(user: User, twofa_enabled: bool) -> None:
    """核心判定（纯函数，便于单测）：管理员且未启用 2FA 即拒绝。"""
    if is_admin_role(user) and not twofa_enabled:
        raise ValidationException(
            message="管理员必须先启用两步验证（2FA）才能访问管理后台",
            error_code=ErrorCode.Auth.TWO_FACTOR_NOT_SETUP,
        )


def require_admin_2fa() -> Admin2FARequired:
    """构造管理员强制 2FA 依赖，套用于 admin 高危面路由。"""
    return Admin2FARequired()
