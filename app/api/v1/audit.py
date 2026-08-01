"""审计日志查询 API（只读）+ 删除（仅 root）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Path, Query, Request

from app.core.exceptions import (
    AuthorizationException,
    ErrorCode,
    NotFoundException,
)
from app.core.request_context import get_client_meta
from app.dependencies import get_current_active_user
from app.dependencies_services import get_audit_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.audit import AuditLogItem
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.services.audit_service import AuditService

router = APIRouter()


def _require_root(user: User) -> None:
    """审计日志删除为 root 专属操作（审计日志查看/删除权限矩阵）。"""
    if not user.is_superuser:
        raise AuthorizationException(
            message="仅超级管理员可删除审计日志",
            error_code=ErrorCode.Authorization.PERMISSION_DENIED,
        )


@router.get(
    "/logs",
    response_model=PaginatedResponse[AuditLogItem],
    dependencies=[Depends(require_permission("system", "logs"))],
)
async def list_audit_logs(
    pagination: PaginationParams = Depends(),
    action: Optional[str] = Query(None, description="动作，如 user.create"),
    resource_type: Optional[str] = Query(None, description="资源类型，如 user/role"),
    resource_id: Optional[str] = Query(None),
    actor_id: Optional[int] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    svc: AuditService = Depends(get_audit_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """分页查询审计日志（需要 system:logs）。"""
    rows, total = await svc.list_logs(
        skip=pagination.skip,
        limit=pagination.limit,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_id=actor_id,
        start_date=start_date,
        end_date=end_date,
    )
    items = [AuditLogItem.model_validate(svc.to_item_dict(r)) for r in rows]
    return PaginatedResponse(
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.get(
    "/logs/{log_id}",
    response_model=AuditLogItem,
    dependencies=[Depends(require_permission("system", "logs"))],
)
async def get_audit_log(
    log_id: int = Path(..., ge=1),
    svc: AuditService = Depends(get_audit_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """审计日志详情（需要 system:logs）。"""
    row = await svc.get_log(log_id)
    if row is None:
        raise NotFoundException(resource_type="审计日志", resource_id=log_id)
    return AuditLogItem.model_validate(svc.to_item_dict(row))


@router.delete("/logs/{log_id}")
async def delete_audit_log(
    log_id: int = Path(..., ge=1),
    request: Request = None,  # type: ignore[assignment]
    svc: AuditService = Depends(get_audit_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """删除单条审计日志（仅 root）。"""
    _require_root(current_user)
    if not await svc.delete_log(log_id):
        raise NotFoundException(resource_type="审计日志", resource_id=log_id)
    await svc.record(
        action="audit.delete",
        resource_type="audit_log",
        resource_id=str(log_id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        **get_client_meta(request),
    )
    return {"ok": True}


@router.delete("/logs")
async def delete_audit_logs_before(
    before: datetime = Query(...),
    request: Request = None,  # type: ignore[assignment]
    svc: AuditService = Depends(get_audit_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """批量删除早于指定时间的审计日志（仅 root）。"""
    _require_root(current_user)
    count = await svc.delete_logs_before(before)
    await svc.record(
        action="audit.delete_bulk",
        resource_type="audit_log",
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"before": before.isoformat(), "deleted_count": count},
        **get_client_meta(request),
    )
    return {"ok": True, "count": count}
