"""异常日志仓储层：CRUD 与列表查询。

统计查询见 ``exception_log_stats``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, asc, delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.exception_log import ExceptionLog
from app.repositories.base import dml_rowcount
from app.repositories.exception_log_stats import fetch_exception_statistics
from app.repositories.base import paginate


class ExceptionLogRepository:
    """异常日志仓储"""

    # 允许排序的字段白名单，避免把任意用户输入映射到 ORM 列
    _SORTABLE_FIELDS = {
        "id",
        "created_at",
        "status_code",
        "exception_type",
        "error_code",
        "severity",
        "priority",
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_exception_log(
        self, exception_log_data: Dict[str, Any]
    ) -> ExceptionLog:
        """创建异常日志记录。"""
        if isinstance(exception_log_data.get("created_at"), str):
            exception_log_data["created_at"] = datetime.fromisoformat(
                exception_log_data["created_at"]
            )

        exception_log = ExceptionLog(**exception_log_data)
        self.db.add(exception_log)
        await self.db.flush()
        await self.db.refresh(exception_log)
        return exception_log

    async def get_exception_log_by_id(self, log_id: int) -> Optional[ExceptionLog]:
        """通过 ID 获取异常日志。"""
        result = await self.db.execute(
            select(ExceptionLog).where(ExceptionLog.id == log_id)
        )
        return result.scalar_one_or_none()

    async def get_exception_log_by_traceback_id(
        self, traceback_id: str
    ) -> Optional[ExceptionLog]:
        """通过跟踪 ID 获取异常日志。"""
        result = await self.db.execute(
            select(ExceptionLog).where(ExceptionLog.traceback_id == traceback_id)
        )
        return result.scalar_one_or_none()

    async def get_exception_logs(
        self,
        skip: int = 0,
        limit: int = 100,
        exception_type: Optional[str] = None,
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
        user_id: Optional[str] = None,
        is_resolved: Optional[bool] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> Tuple[List[ExceptionLog], int]:
        """获取异常日志列表（筛选 + 分页 + 排序）。"""
        conditions = []

        if exception_type:
            conditions.append(ExceptionLog.exception_type == exception_type)
        if error_code:
            conditions.append(ExceptionLog.error_code == error_code)
        if status_code:
            conditions.append(ExceptionLog.status_code == status_code)
        if user_id:
            conditions.append(ExceptionLog.user_id == user_id)
        if is_resolved is not None:
            conditions.append(ExceptionLog.is_resolved == is_resolved)
        if start_date:
            conditions.append(ExceptionLog.created_at >= start_date)
        if end_date:
            conditions.append(ExceptionLog.created_at <= end_date)

        query = select(ExceptionLog)
        count_query = select(func.count(ExceptionLog.id))

        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        sort_by = sort_by if sort_by in self._SORTABLE_FIELDS else "created_at"
        sort_column = getattr(ExceptionLog, sort_by)
        if sort_order.lower() == "desc":
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(asc(sort_column))

        total_result = await self.db.execute(count_query)
        total = int(total_result.scalar() or 0)

        result = await self.db.execute(paginate(query, skip, limit))
        exception_logs = result.scalars().all()

        return list(exception_logs), total

    async def update_exception_log(
        self, log_id: int, update_data: Dict[str, Any]
    ) -> Optional[ExceptionLog]:
        """更新异常日志。"""
        result = await self.db.execute(
            select(ExceptionLog).where(ExceptionLog.id == log_id)
        )
        exception_log = result.scalar_one_or_none()

        if not exception_log:
            return None

        for field, value in update_data.items():
            if hasattr(exception_log, field):
                setattr(exception_log, field, value)

        await self.db.flush()
        await self.db.refresh(exception_log)
        return exception_log

    async def resolve_exception_log(
        self,
        log_id: int,
        resolved_by: str,
        resolution_notes: Optional[str] = None,
    ) -> Optional[ExceptionLog]:
        """标记异常日志为已解决。"""
        return await self.update_exception_log(
            log_id=log_id,
            update_data={
                "is_resolved": True,
                "resolved_at": now_utc(),
                "resolved_by": resolved_by,
                "resolution_notes": resolution_notes,
            },
        )

    async def delete_exception_log(self, log_id: int) -> bool:
        """删除异常日志。"""
        result = await self.db.execute(
            delete(ExceptionLog).where(ExceptionLog.id == log_id)
        )
        await self.db.flush()
        return dml_rowcount(result) > 0

    async def delete_before(self, cutoff: datetime) -> int:
        """删除保留期以前的异常日志（flush，未 commit）。"""
        result = await self.db.execute(
            delete(ExceptionLog).where(ExceptionLog.created_at < cutoff)
        )
        await self.db.flush()
        return dml_rowcount(result)

    async def get_exception_statistics(
        self, time_window_hours: int = 24
    ) -> Dict[str, Any]:
        """获取异常统计信息（委托 ``exception_log_stats``）。"""
        return await fetch_exception_statistics(self.db, time_window_hours)
