"""财务作用范围：finance:* 权限与峰范围解耦，读写在服务层复用。

规则：
- 超级用户或持 ``all`` 绑定的账号：全范围（None）。
- 仅持 ``peak`` 绑定的账号：只能读写绑定峰的资金。
- 无任何可用范围：拒绝（不把「没有范围」当作全范围）。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationException, ErrorCode
from app.models.user import User
from app.repositories.organization_repo import OrganizationRepository


async def resolve_allowed_peak_ids(
    db: AsyncSession, actor: User
) -> Optional[set[int]]:
    """返回可访问的峰 id 集合；None 表示全范围。"""
    if actor.is_superuser:
        return None
    scopes = await OrganizationRepository(db).get_role_scopes(actor.id)
    if any(item["scope_type"] == "all" for item in scopes):
        return None
    peak_ids = {
        item["scope_peak_id"]
        for item in scopes
        if item["scope_type"] == "peak" and item["scope_peak_id"]
    }
    if not peak_ids:
        raise AuthorizationException(
            message="没有可访问的财务范围",
            error_code=ErrorCode.Authorization.SCOPE_FORBIDDEN,
        )
    return peak_ids


def ensure_peak_in_scope(
    peak_id: Optional[int], allowed: Optional[set[int]]
) -> None:
    """峰范围校验：allowed=None 放行，否则要求峰在集合内。"""
    if allowed is None:
        return
    if peak_id is None or peak_id not in allowed:
        raise AuthorizationException(
            message="目标峰不在授权范围内",
            error_code=ErrorCode.Authorization.SCOPE_FORBIDDEN,
            details={"peak_id": peak_id},
        )
