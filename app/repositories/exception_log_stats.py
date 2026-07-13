"""异常日志统计查询（从 ExceptionLogRepository 抽出的只读聚合）。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.exception_log import ExceptionLog


async def fetch_exception_statistics(
    db: AsyncSession, time_window_hours: int = 24
) -> Dict[str, Any]:
    """按时间窗口聚合异常日志统计。

    Args:
        db: 异步会话。
        time_window_hours: 统计窗口（小时）。

    Returns:
        含 total / by_type / by_error_code / by_status_code / by_user 的字典。
    """
    cutoff_time = now_utc() - timedelta(hours=time_window_hours)

    total_result = await db.execute(
        select(func.count(ExceptionLog.id)).where(
            ExceptionLog.created_at >= cutoff_time
        )
    )
    total = total_result.scalar()

    type_result = await db.execute(
        select(
            ExceptionLog.exception_type,
            func.count(ExceptionLog.id).label("count"),
        )
        .where(ExceptionLog.created_at >= cutoff_time)
        .group_by(ExceptionLog.exception_type)
        .order_by(desc("count"))
        .limit(10)
    )
    by_type = {row.exception_type: row.count for row in type_result}

    error_code_result = await db.execute(
        select(ExceptionLog.error_code, func.count(ExceptionLog.id).label("count"))
        .where(ExceptionLog.created_at >= cutoff_time)
        .group_by(ExceptionLog.error_code)
        .order_by(desc("count"))
        .limit(10)
    )
    by_error_code = {
        row.error_code: row.count for row in error_code_result if row.error_code
    }

    status_code_result = await db.execute(
        select(ExceptionLog.status_code, func.count(ExceptionLog.id).label("count"))
        .where(ExceptionLog.created_at >= cutoff_time)
        .group_by(ExceptionLog.status_code)
        .order_by(desc("count"))
    )
    by_status_code = {
        row.status_code: row.count for row in status_code_result if row.status_code
    }

    user_result = await db.execute(
        select(ExceptionLog.user_id, func.count(ExceptionLog.id).label("count"))
        .where(ExceptionLog.created_at >= cutoff_time)
        .group_by(ExceptionLog.user_id)
        .order_by(desc("count"))
        .limit(10)
    )
    by_user = {row.user_id: row.count for row in user_result if row.user_id}

    return {
        "time_window_hours": time_window_hours,
        "total_exceptions": total,
        "by_exception_type": by_type,
        "by_error_code": by_error_code,
        "by_status_code": by_status_code,
        "by_user": by_user,
    }
