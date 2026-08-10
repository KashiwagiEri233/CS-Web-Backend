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
from app.dependencies_services import get_user_service
from app.middleware.rbac import require_admin_2fa, require_permission
from app.models.user import User
from app.schemas.auth import UserOut
from app.schemas.user import AdminUserListOut, AdminUserOut, AdminUserUpdate
from app.services.user_service import UserService

router = APIRouter(dependencies=[Depends(require_admin_2fa)])


def _to_admin_out(user: User) -> dict:
    """UserOut + roles（前端管理员视图需要角色列表）。"""
    base = UserOut.model_validate(user).model_dump()
    base["roles"] = [r.name for r in user.roles]
    return base


def _is_admin(user: User) -> bool:
    """是否管理员（admin 角色或超级用户）。"""
    return user.is_superuser or any(r.name == "admin" for r in user.roles)


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
    return _to_admin_out(user)


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
    return _to_admin_out(user)


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
    return _to_admin_out(user)


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
