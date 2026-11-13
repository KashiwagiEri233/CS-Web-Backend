"""管理员用户管理 API：列表/详情/编辑/禁用/启用/重置密码/删除。

保护规则（与前端 admin 语义对齐）：
- SELF_DISABLE / SELF_DELETE：不能禁用/删除自己
- ROOT_PROTECTED：超级管理员账号不可被修改/禁用/删除
- FORBIDDEN：普通管理员不可操作其他管理员
- LAST_ADMIN：不能禁用/删除最后一个活跃管理员
- 重置密码后同事务撤销全部 refresh + password_changed_at（旧 access 失效）
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request

from app.core.request_context import get_client_meta
from app.dependencies_services import get_audit_service, get_rbac_service, get_user_service
from app.middleware.rbac import require_admin_2fa, require_permission
from app.models.user import User
from app.schemas.auth import UserOut
from app.schemas.rbac import RoleBindingsReplace, UserBindingsResponse
from app.schemas.user import AdminUserListOut, AdminUserOut, AdminUserUpdate
from app.services.audit_service import AuditService
from app.services.rbac.rbac_service import RBACService
from app.services.user.user_service import UserService, to_admin_out

router = APIRouter(dependencies=[Depends(require_admin_2fa())])


def _is_admin(user: User) -> bool:
    """是否管理员（admin 角色或超级用户）。"""
    return user.is_superuser or any(r.name == "admin" for r in user.roles)


def _parse_if_match(request: Request) -> Optional[int]:
    """解析 If-Match（带引号的整数 version）；缺失返回 None 由服务层返回 428。"""
    raw = request.headers.get("If-Match")
    if not raw:
        return None
    value = raw.strip().strip('"')
    try:
        return int(value)
    except ValueError:
        return None


@router.get("/{user_id}/role-bindings", response_model=UserBindingsResponse)
async def get_user_role_bindings(
    user_id: int,
    rbac_service: RBACService = Depends(get_rbac_service),
    current_user: User = Depends(require_permission("user", "manage_roles")),
) -> Any:
    """读取用户的角色绑定与授权版本（需要 user:manage_roles）。"""
    version = await rbac_service.get_user_authorization_version(user_id)
    if version is None:
        from app.core.exceptions import NotFoundException

        raise NotFoundException(
            message="用户不存在", resource_type="user", resource_id=user_id
        )
    return UserBindingsResponse(
        user_id=user_id,
        authorization_version=version,
        bindings=await rbac_service.get_user_bindings(user_id),
    )


@router.put("/{user_id}/role-bindings", response_model=UserBindingsResponse)
async def replace_user_role_bindings(
    user_id: int,
    body: RoleBindingsReplace,
    request: Request,
    rbac_service: RBACService = Depends(get_rbac_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("user", "manage_roles")),
) -> Any:
    """整组替换用户角色绑定（If-Match 版本 + 防提权 + 同事务审计）。"""
    bindings = await rbac_service.replace_user_role_bindings(
        user_id,
        [item.model_dump() for item in body.bindings],
        actor=current_user,
        expected_version=_parse_if_match(request),
        commit=False,
    )
    await audit.record_atomic(
        action="user.replace_role_bindings",
        resource_type="user",
        resource_id=str(user_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"bindings": [item.model_dump() for item in body.bindings]},
        **get_client_meta(request),
    )
    version = await rbac_service.get_user_authorization_version(user_id) or 1
    return UserBindingsResponse(
        user_id=user_id, authorization_version=version, bindings=bindings
    )


@router.get("", response_model=AdminUserListOut)
async def list_users(
    search: Optional[str] = None,
    role: str = "all",
    active: str = "all",
    page: int = 1,
    page_size: int = Query(50, alias="pageSize"),
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(require_permission("user", "list")),
) -> Any:
    """用户列表（搜索/角色/激活筛选，不含密码字段）。"""
    return await user_service.list_users_admin(
        search=search, role=role, active=active, page=page, page_size=page_size
    )


@router.get("/{user_id}", response_model=UserOut)
async def get_user_detail(
    user_id: int,
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(require_permission("user", "read")),
) -> Any:
    """用户详情（管理员）。"""
    return await user_service.get_user(user_id)


@router.put("/{user_id}", response_model=AdminUserOut)
async def update_user_admin(
    user_id: int,
    body: AdminUserUpdate,
    request: Request,
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(require_permission("user", "update")),
) -> Any:
    """编辑用户（仅超级用户可改角色/is_active；普通管理员仅资料字段）。"""
    user = await user_service.update_user_admin(
        current_user, user_id, body, client_meta=get_client_meta(request)
    )
    return to_admin_out(user)


@router.post("/{user_id}/disable", response_model=AdminUserOut)
async def disable_user(
    user_id: int,
    request: Request,
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(require_permission("user", "update")),
) -> Any:
    """禁用用户（普通管理员不可操作其他管理员）。"""
    user = await user_service.set_user_active_admin(
        current_user, user_id, active=False, client_meta=get_client_meta(request)
    )
    return to_admin_out(user)


@router.post("/{user_id}/enable", response_model=AdminUserOut)
async def enable_user(
    user_id: int,
    request: Request,
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(require_permission("user", "update")),
) -> Any:
    """启用用户。"""
    user = await user_service.set_user_active_admin(
        current_user, user_id, active=True, client_meta=get_client_meta(request)
    )
    return to_admin_out(user)


@router.post("/{user_id}/reset-password-default")
async def reset_password_default(
    user_id: int,
    request: Request,
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(require_permission("user", "update")),
) -> Any:
    """重置为默认密码（PASSWORD_RESET_DEFAULT；仅普通用户目标，普通管理员可用）。"""
    await user_service.reset_password_admin(
        current_user,
        user_id,
        default_password=True,
        client_meta=get_client_meta(request),
    )
    return {"ok": True}


@router.post("/{user_id}/reset-password")
async def reset_password_custom(
    user_id: int,
    request: Request,
    body: dict,
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(require_permission("user", "update")),
) -> Any:
    """自定义重置密码（仅超级用户；body: {password}）。"""
    from app.schemas.user import CustomResetPassword

    payload = CustomResetPassword.model_validate(body)
    await user_service.reset_password_admin(
        current_user,
        user_id,
        default_password=False,
        new_password=payload.password,
        client_meta=get_client_meta(request),
    )
    return {"ok": True}


@router.delete("/{user_id}")
async def delete_user_admin(
    user_id: int,
    request: Request,
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(require_permission("user", "delete")),
) -> Any:
    """硬删除用户（仅超级用户；保护规则见模块 docstring）。"""
    await user_service.delete_user_admin(
        current_user, user_id, client_meta=get_client_meta(request)
    )
    return {"ok": True}
