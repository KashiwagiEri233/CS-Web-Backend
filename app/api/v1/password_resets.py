"""密码重置申请管理 API（管理员）：列表 / 批准 / 拒绝。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request

from app.core.request_context import get_client_meta
from app.dependencies_services import get_auth_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.password_reset import ResetRequestOut, ResetRequestResolve
from app.services.auth.auth_service import AuthService
from app.services.password_reset_service import PasswordResetService

router = APIRouter()


def _get_reset_service(auth_service: AuthService) -> PasswordResetService:
    return PasswordResetService(auth_service.db, audit=auth_service.audit)


@router.get("", response_model=list[ResetRequestOut])
async def list_reset_requests(
    status: Optional[str] = None,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(require_permission("password_reset", "read")),
) -> Any:
    """密码重置申请列表（支持 status 筛选）。"""
    service = _get_reset_service(auth_service)
    return await service.list_requests(status)


@router.post("/{request_id}/approve", response_model=ResetRequestOut)
async def approve_reset_request(
    request_id: int,
    request: Request,
    body: ResetRequestResolve,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(require_permission("password_reset", "approve")),
) -> Any:
    """批准密码重置申请：重置为默认密码 + 撤销全部会话。"""
    service = _get_reset_service(auth_service)
    return await service.approve_request(
        request_id,
        admin_id=current_user.id,
        admin_username=current_user.username,
        note=body.note,
        client_meta=get_client_meta(request),
    )


@router.post("/{request_id}/reject", response_model=ResetRequestOut)
async def reject_reset_request(
    request_id: int,
    request: Request,
    body: ResetRequestResolve,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(require_permission("password_reset", "approve")),
) -> Any:
    """拒绝密码重置申请。"""
    service = _get_reset_service(auth_service)
    return await service.reject_request(
        request_id,
        admin_id=current_user.id,
        admin_username=current_user.username,
        note=body.note,
        client_meta=get_client_meta(request),
    )
