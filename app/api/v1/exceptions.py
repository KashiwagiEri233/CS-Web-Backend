"""
异常管理 API
只保留核心端点：查询日志、查看详情、标记解决。
模式识别/告警/指标端点已移除。
"""

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Path, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.middleware.rbac import require_permission
from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.user import User
from app.repositories.exception_log_repo import ExceptionLogRepository
from app.services.exception_service import ExceptionService

router = APIRouter()


@router.get("/logs", dependencies=[Depends(require_permission("exception", "read"))])
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """获取异常日志列表。"""
    svc = ExceptionService(db)
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
    return {"logs": [log.to_dict() for log in logs], "total": total, "skip": skip, "limit": limit}


@router.get("/logs/{log_id}", dependencies=[Depends(require_permission("exception", "read"))])
async def get_exception_log(
    log_id: int = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """获取单个异常日志详情。"""
    repo = ExceptionLogRepository(db)
    log = await repo.get_exception_log_by_id(log_id)
    if not log:
        raise NotFoundException(resource_type="异常日志", resource_id=log_id)
    return log.to_dict()


@router.put("/logs/{log_id}/resolve", dependencies=[Depends(require_permission("exception", "resolve"))])
async def resolve_exception_log(
    log_id: int = Path(...),
    resolution_notes: Optional[str] = Body(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """标记异常日志为已解决。"""
    svc = ExceptionService(db)
    log = await svc.resolve_exception(
        log_id=log_id,
        resolved_by=current_user.username,
        resolution_notes=resolution_notes,
    )
    if not log:
        raise NotFoundException(resource_type="异常日志", resource_id=log_id)
    return {"message": "异常已解决", "log": log.to_dict()}
