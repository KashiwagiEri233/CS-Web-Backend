"""
异常管理API端点
提供异常日志查询、统计和管理功能
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Path, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BusinessException,
    NotFoundException,
    PermissionDeniedException
)
from app.middleware.rbac import require_permission
from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.user import User
from app.repositories.exception_log_repo import ExceptionLogRepository
from app.services.exception_service import ExceptionService

router = APIRouter()


@router.get("/logs", dependencies=[Depends(require_permission("exception", "read"))])
async def get_exception_logs(
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=1000, description="限制记录数"),
    exception_type: Optional[str] = Query(None, description="异常类型筛选"),
    error_code: Optional[str] = Query(None, description="错误代码筛选"),
    status_code: Optional[int] = Query(None, description="状态码筛选"),
    user_id: Optional[str] = Query(None, description="用户ID筛选"),
    is_resolved: Optional[bool] = Query(None, description="是否已解决筛选"),
    start_date: Optional[datetime] = Query(None, description="开始日期"),
    end_date: Optional[datetime] = Query(None, description="结束日期"),
    sort_by: str = Query("created_at", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    获取异常日志列表
    """
    # 创建服务实例
    exception_service = ExceptionService(db)
    
    # 获取异常日志
    logs, total = await exception_service.get_exception_logs(
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
        sort_order=sort_order
    )
    
    return {
        "logs": [log.to_dict() for log in logs],
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/logs/{log_id}", dependencies=[Depends(require_permission("exception", "read"))])
async def get_exception_log(
    log_id: int = Path(..., description="日志ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    获取单个异常日志详情
    """
    # 创建仓储实例
    log_repo = ExceptionLogRepository(db)
    
    # 获取异常日志
    log = await log_repo.get_exception_log_by_id(log_id)
    
    if not log:
        raise NotFoundException(
            resource_type="异常日志",
            resource_id=log_id
        )
    
    return log.to_dict()


@router.put("/logs/{log_id}/resolve", dependencies=[Depends(require_permission("exception", "resolve"))])
async def resolve_exception_log(
    log_id: int = Path(..., description="日志ID"),
    resolution_notes: Optional[str] = Body(None, description="解决备注"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    解决异常日志
    """
    # 创建服务实例
    exception_service = ExceptionService(db)
    
    # 解决异常
    log = await exception_service.resolve_exception(
        log_id=log_id,
        resolved_by=current_user.username,
        resolution_notes=resolution_notes
    )
    
    if not log:
        raise NotFoundException(
            resource_type="异常日志",
            resource_id=log_id
        )
    
    return {
        "message": "异常已解决",
        "log": log.to_dict()
    }


@router.get("/statistics", dependencies=[Depends(require_permission("exception", "statistics"))])
async def get_exception_statistics(
    time_window_hours: int = Query(24, ge=1, le=168, description="时间窗口（小时）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    获取异常统计信息
    """
    # 创建服务实例
    exception_service = ExceptionService(db)
    
    # 获取统计信息
    stats = await exception_service.get_exception_statistics(time_window_hours)
    
    return stats


@router.get("/patterns", dependencies=[Depends(require_permission("exception", "analyze"))])
async def analyze_exception_patterns(
    time_window_hours: int = Query(24, ge=1, le=168, description="时间窗口（小时）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    分析异常模式
    """
    # 创建服务实例
    exception_service = ExceptionService(db)
    
    # 分析异常模式
    patterns = await exception_service.analyze_exception_patterns(time_window_hours)
    
    return patterns


@router.get("/anomalies", dependencies=[Depends(require_permission("exception", "analyze"))])
async def detect_anomalies(
    baseline_window_hours: int = Query(168, ge=24, le=720, description="基准时间窗口（小时）"),
    current_window_hours: int = Query(1, ge=1, le=24, description="当前时间窗口（小时）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    检测异常模式
    """
    # 创建服务实例
    exception_service = ExceptionService(db)
    
    # 检测异常
    anomalies = await exception_service.detect_anomalies(
        baseline_window_hours=baseline_window_hours,
        current_window_hours=current_window_hours
    )
    
    return anomalies


@router.get("/metrics", dependencies=[Depends(require_permission("exception", "metrics"))])
async def get_exception_metrics(
    time_window_hours: int = Query(24, ge=1, le=168, description="时间窗口（小时）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    获取异常指标
    """
    # 创建服务实例
    exception_service = ExceptionService(db)
    
    # 获取指标
    metrics = await exception_service.collect_metrics(time_window_hours)
    
    return metrics


@router.get("/alerts", dependencies=[Depends(require_permission("exception", "alerts"))])
async def get_exception_alerts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    获取异常告警
    """
    # 创建服务实例
    exception_service = ExceptionService(db)
    
    # 获取活跃告警
    alerts = await exception_service.get_active_alerts()
    
    return {
        "alerts": [alert.to_dict() for alert in alerts]
    }


@router.put("/alerts/{alert_id}/acknowledge", dependencies=[Depends(require_permission("exception", "alerts"))])
async def acknowledge_exception_alert(
    alert_id: int = Path(..., description="告警ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    确认异常告警
    """
    # 创建服务实例
    exception_service = ExceptionService(db)
    
    # 确认告警
    alert = await exception_service.acknowledge_alert(
        alert_id=alert_id,
        acknowledged_by=current_user.username
    )
    
    if not alert:
        raise NotFoundException(
            resource_type="异常告警",
            resource_id=alert_id
        )
    
    return {
        "message": "告警已确认",
        "alert": alert.to_dict()
    }


@router.put("/alerts/{alert_id}/resolve", dependencies=[Depends(require_permission("exception", "alerts"))])
async def resolve_exception_alert(
    alert_id: int = Path(..., description="告警ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    解决异常告警
    """
    # 创建服务实例
    exception_service = ExceptionService(db)
    
    # 解决告警
    alert = await exception_service.resolve_alert(
        alert_id=alert_id,
        resolved_by=current_user.username
    )
    
    if not alert:
        raise NotFoundException(
            resource_type="异常告警",
            resource_id=alert_id
        )
    
    return {
        "message": "告警已解决",
        "alert": alert.to_dict()
    }


@router.get("/dashboard", dependencies=[Depends(require_permission("exception", "dashboard"))])
async def get_exception_dashboard(
    time_window_hours: int = Query(24, ge=1, le=168, description="时间窗口（小时）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    获取异常仪表板数据
    """
    # 创建服务实例
    exception_service = ExceptionService(db)
    
    # 并行获取各种数据
    import asyncio
    
    # 获取统计数据
    stats = await exception_service.get_exception_statistics(time_window_hours)
    
    # 获取异常模式
    patterns = await exception_service.analyze_exception_patterns(time_window_hours)
    
    # 获取异常指标
    metrics = await exception_service.collect_metrics(time_window_hours)
    
    # 获取活跃告警
    alerts = await exception_service.get_active_alerts()
    
    # 获取最近的异常日志
    recent_logs, _ = await exception_service.get_exception_logs(
        skip=0,
        limit=10,
        sort_by="created_at",
        sort_order="desc"
    )
    
    return {
        "statistics": stats,
        "patterns": patterns,
        "metrics": metrics,
        "alerts": [alert.to_dict() for alert in alerts],
        "recent_logs": [log.to_dict() for log in recent_logs]
    }