from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.request_context import get_client_meta
from app.dependencies import get_current_active_user
from app.dependencies_services import (
    get_audit_service,
    get_auth_service,
    get_user_service,
)
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.user import UserCreate, UserResponse, UserUpdate
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.user_service import UserService

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[UserResponse])
async def read_users(
    pagination: PaginationParams = Depends(),
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(require_permission("user", "list")),
) -> Any:
    """获取用户列表（需要 user:list 权限，分页）"""
    users, total = await user_service.list_users(
        skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=users, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.get("/me", response_model=UserResponse)
async def read_user_me(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """获取当前用户信息"""
    return current_user


@router.get("/{user_id}", response_model=UserResponse)
async def read_user(
    user_id: int,
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(require_permission("user", "read")),
) -> Any:
    """获取指定用户信息（需要 user:read）"""
    return await user_service.get_user(user_id)


@router.post("/", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(require_permission("user", "create")),
) -> Any:
    """创建用户（需要 user:create）。创建 + 审计 + 提交走 service 原子入口。"""
    return await auth_service.create_user_with_audit(
        user_data,
        actor=current_user,
        client_meta=get_client_meta(request),
        via="users.create",
    )


@router.put("/me", response_model=UserResponse)
async def update_user_me(
    user_data: UserUpdate,
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """更新当前用户资料（不可改 is_active）。"""
    return await user_service.update_profile(
        current_user, user_data.model_dump(exclude_unset=True)
    )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    request: Request,
    user_service: UserService = Depends(get_user_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("user", "update")),
) -> Any:
    """更新用户（改密与撤 refresh 同事务）。"""
    updated = await user_service.update_user(
        user_id,
        user_data.model_dump(exclude_unset=True),
        commit=False,
        actor=current_user,
    )
    meta = get_client_meta(request)
    await audit.record_atomic(
        action="user.update",
        resource_type="user",
        resource_id=str(user_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"fields": list(user_data.model_dump(exclude_unset=True).keys())},
        **meta,
    )
    return updated


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    user_service: UserService = Depends(get_user_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("user", "delete")),
) -> Any:
    """软删除用户（需要 user:delete）。"""
    await user_service.delete_user(user_id, actor=current_user, commit=False)
    meta = get_client_meta(request)
    await audit.record_atomic(
        action="user.delete",
        resource_type="user",
        resource_id=str(user_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        **meta,
    )
    return {"message": "用户已删除"}
