"""功能模块可见性 API。

- GET  /feature-visibility               — 公开读取全部模块可见性（供导航渲染）
- PUT  /admin/feature-visibility/{key}   — root 更新单模块（强制 2FA + 审计）

读取公开：可见性规则本身不含敏感信息，真实权限闸门仍在 BFF/后端路由层，
前端隐藏不等于接口不可达（保持现有安全模型）。写入严格 root 专属 + 2FA。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Request

from app.core.exceptions import (
    AuthorizationException,
    ErrorCode,
    NotFoundException,
    ValidationException,
)
from app.core.request_context import get_client_meta
from app.dependencies import get_current_active_user
from app.dependencies_services import (
    get_audit_service,
    get_feature_visibility_service,
    get_totp_service,
)
from app.models.user import User
from app.schemas.feature_visibility import (
    FeatureVisibilityConfig,
    ModuleVisibility,
    UpdateVisibilityRequest,
    VisibilityRule,
)
from app.services.audit_service import AuditService
from app.services.feature_visibility_service import (
    FeatureVisibilityService,
    KNOWN_MODULE_KEYS,
)

router = APIRouter()


def _require_root(user: User) -> None:
    """功能模块可见性写入为 root 专属操作。"""
    if not user.is_superuser:
        raise AuthorizationException(
            message="仅超级管理员可管理功能模块可见性",
            error_code=ErrorCode.Authorization.PERMISSION_DENIED,
        )


@router.get(
    "/feature-visibility",
    response_model=FeatureVisibilityConfig,
    summary="获取功能模块可见性配置",
)
async def get_feature_visibility(
    svc: FeatureVisibilityService = Depends(get_feature_visibility_service),
) -> Any:
    """公开读取全部受管模块的可见性规则（缺失项回退默认值）。"""
    return await svc.get_config()


@router.put(
    "/admin/feature-visibility/{module_key}",
    response_model=ModuleVisibility,
    summary="更新单模块可见性（root + 2FA）",
)
async def update_feature_visibility(
    body: UpdateVisibilityRequest,
    request: Request,
    module_key: str = Path(..., min_length=1, max_length=50),
    current_user: User = Depends(get_current_active_user),
    svc: FeatureVisibilityService = Depends(get_feature_visibility_service),
    audit: AuditService = Depends(get_audit_service),
    totp: TOTPService = Depends(get_totp_service),
) -> Any:
    """更新单模块可见性。

    - root 专属（is_superuser）
    - 强制 2FA（决策 B）：root 必须已启用 2FA，否则拒绝；并校验 TOTP 码
    - 审计留痕：服务端推导 actor，记录新旧规则
    """
    _require_root(current_user)

    if module_key not in KNOWN_MODULE_KEYS:
        raise NotFoundException(resource_type="feature_module", resource_id=module_key)

    # 强制 2FA：未启用直接拒绝，不允许「未启用直接放行」绕过。
    if not await totp.is_enabled(current_user.id):
        raise ValidationException(
            message="请先启用两步验证后再管理功能模块可见性",
            error_code=ErrorCode.Auth.TWO_FACTOR_NOT_SETUP,
        )
    await totp.verify_or_raise(current_user.id, body.totp_code)

    new_rule = VisibilityRule(guest=body.guest, member=body.member, admin=body.admin)
    old, new = await svc.update_module(module_key, new_rule)

    # 业务变更 + 审计同事务原子提交（record_atomic 内部 commit 共享会话）。
    await audit.record_atomic(
        action="feature_visibility.update",
        resource_type="feature_module",
        resource_id=module_key,
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={
            "old": {"guest": old.guest, "member": old.member, "admin": old.admin},
            "new": {"guest": new.guest, "member": new.member, "admin": new.admin},
        },
        **get_client_meta(request),
    )
    return new
