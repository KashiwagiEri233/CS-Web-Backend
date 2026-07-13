"""异常管理 API：查询日志、查看详情、标记解决。"""

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Path, Query

from app.core.exceptions import NotFoundException
from app.dependencies import get_current_active_user
from app.dependencies_services import get_exception_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.exception_log import ExceptionLogItem, ExceptionLogResolveResponse
from app.schemas.pagination import PaginatedResponse
from app.services.exception_service import ExceptionService

router = APIRouter()


@router.get(
    "/logs",
    response_model=PaginatedResponse[ExceptionLogItem],
    dependencies=[Depends(require_permission("exception", "read"))],
)
async def get_exception_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    exception_type: Optional[str] = Query(None),
    error_code: Optional[str] = Query(None),
    status_code: Optional[int] = Query(None),
    user_id: Optional[str] = Query(None),
    is_resolved: Optional[bool] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    svc: ExceptionService = Depends(get_exception_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """获取异常日志列表（统一分页）。"""
    logs, total = await svc.get_exception_logs(
        skip=skip,
        limit=limit,
        exception_type=exception_type,
        error_code=error_code,
        status_code=status_code,
        user_id=user_id,
        is_resolved=is_resolved,
        start_date=start_date,
        end_date=end_date,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    items = [ExceptionLogItem.model_validate(log.to_dict()) for log in logs]
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@router.get(
    "/logs/{log_id}",
    response_model=ExceptionLogItem,
    dependencies=[Depends(require_permission("exception", "read"))],
)
async def get_exception_log(
    log_id: int = Path(...),
    svc: ExceptionService = Depends(get_exception_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """获取单个异常日志详情。"""
    log = await svc.get_exception_log(log_id)
    if not log:
        raise NotFoundException(resource_type="异常日志", resource_id=log_id)
    return ExceptionLogItem.model_validate(log.to_dict())


@router.put(
    "/logs/{log_id}/resolve",
    response_model=ExceptionLogResolveResponse,
    dependencies=[Depends(require_permission("exception", "resolve"))],
)
async def resolve_exception_log(
    log_id: int = Path(...),
    resolution_notes: Optional[str] = Body(None),
    svc: ExceptionService = Depends(get_exception_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """标记异常日志为已解决。"""
    log = await svc.resolve_exception(
        log_id=log_id,
        resolved_by=current_user.username,
        resolution_notes=resolution_notes,
    )
    if not log:
        raise NotFoundException(resource_type="异常日志", resource_id=log_id)
    return ExceptionLogResolveResponse(
        log=ExceptionLogItem.model_validate(log.to_dict())
    )
