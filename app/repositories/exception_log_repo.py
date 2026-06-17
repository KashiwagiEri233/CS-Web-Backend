"""
异常日志仓储层
提供异常日志的数据库操作方法
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from sqlalchemy import select, delete, and_, or_, func, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.exception_log import ExceptionLog


class ExceptionLogRepository:
    """异常日志仓储"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_exception_log(
        self, exception_log_data: Dict[str, Any]
    ) -> ExceptionLog:
        """
        创建异常日志记录

        Args:
            exception_log_data: 异常日志数据

        Returns:
            创建的异常日志对象
        """
        # 确保时间戳是datetime对象
        if isinstance(exception_log_data.get("created_at"), str):
            exception_log_data["created_at"] = datetime.fromisoformat(
                exception_log_data["created_at"]
            )

        exception_log = ExceptionLog(**exception_log_data)
        self.db.add(exception_log)
        await self.db.commit()
        await self.db.refresh(exception_log)
        return exception_log

    async def get_exception_log_by_id(self, log_id: int) -> Optional[ExceptionLog]:
        """
        通过ID获取异常日志

        Args:
            log_id: 日志ID

        Returns:
            异常日志对象或None
        """
        result = await self.db.execute(
            select(ExceptionLog).where(ExceptionLog.id == log_id)
        )
        return result.scalar_one_or_none()

    async def get_exception_log_by_traceback_id(
        self, traceback_id: str
    ) -> Optional[ExceptionLog]:
        """
        通过跟踪ID获取异常日志

        Args:
            traceback_id: 跟踪ID

        Returns:
            异常日志对象或None
        """
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
        """
        获取异常日志列表

        Args:
            skip: 跳过记录数
            limit: 限制记录数
            exception_type: 异常类型筛选
            error_code: 错误代码筛选
            status_code: 状态码筛选
            user_id: 用户ID筛选
            is_resolved: 是否已解决筛选
            start_date: 开始日期
            end_date: 结束日期
            sort_by: 排序字段
            sort_order: 排序方向

        Returns:
            异常日志列表和总数
        """
        # 构建查询条件
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

        # 构建基础查询
        query = select(ExceptionLog)
        count_query = select(func.count(ExceptionLog.id))

        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        # 排序
        sort_column = getattr(ExceptionLog, sort_by, ExceptionLog.created_at)
        if sort_order.lower() == "desc":
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(asc(sort_column))

        # 获取总数
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()

        # 分页查询
        result = await self.db.execute(query.offset(skip).limit(limit))
        exception_logs = result.scalars().all()

        return list(exception_logs), total

    async def update_exception_log(
        self, log_id: int, update_data: Dict[str, Any]
    ) -> Optional[ExceptionLog]:
        """
        更新异常日志

        Args:
            log_id: 日志ID
            update_data: 更新数据

        Returns:
            更新后的异常日志对象或None
        """
        result = await self.db.execute(
            select(ExceptionLog).where(ExceptionLog.id == log_id)
        )
        exception_log = result.scalar_one_or_none()

        if not exception_log:
            return None

        for field, value in update_data.items():
            if hasattr(exception_log, field):
                setattr(exception_log, field, value)

        await self.db.commit()
        await self.db.refresh(exception_log)
        return exception_log

    async def resolve_exception_log(
        self, log_id: int, resolved_by: str, resolution_notes: Optional[str] = None
    ) -> Optional[ExceptionLog]:
        """
        解决异常日志

        Args:
            log_id: 日志ID
            resolved_by: 解决人
            resolution_notes: 解决备注

        Returns:
            更新后的异常日志对象或None
        """
        return await self.update_exception_log(
            log_id=log_id,
            update_data={
                "is_resolved": True,
                "resolved_at": datetime.now(timezone.utc),
                "resolved_by": resolved_by,
                "resolution_notes": resolution_notes,
            },
        )

    async def delete_exception_log(self, log_id: int) -> bool:
        """
        删除异常日志

        Args:
            log_id: 日志ID

        Returns:
            是否删除成功
        """
        result = await self.db.execute(
            delete(ExceptionLog).where(ExceptionLog.id == log_id)
        )
        await self.db.commit()
        return result.rowcount > 0

    async def get_exception_statistics(
        self, time_window_hours: int = 24
    ) -> Dict[str, Any]:
        """
        获取异常统计信息

        Args:
            time_window_hours: 时间窗口（小时）

        Returns:
            统计信息
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)

        # 总体统计
        total_result = await self.db.execute(
            select(func.count(ExceptionLog.id)).where(
                ExceptionLog.created_at >= cutoff_time
            )
        )
        total = total_result.scalar()

        # 按异常类型统计
        type_result = await self.db.execute(
            select(
                ExceptionLog.exception_type, func.count(ExceptionLog.id).label("count")
            )
            .where(ExceptionLog.created_at >= cutoff_time)
            .group_by(ExceptionLog.exception_type)
            .order_by(desc("count"))
            .limit(10)
        )
        by_type = {row.exception_type: row.count for row in type_result}

        # 按错误代码统计
        error_code_result = await self.db.execute(
            select(ExceptionLog.error_code, func.count(ExceptionLog.id).label("count"))
            .where(ExceptionLog.created_at >= cutoff_time)
            .group_by(ExceptionLog.error_code)
            .order_by(desc("count"))
            .limit(10)
        )
        by_error_code = {
            row.error_code: row.count for row in error_code_result if row.error_code
        }

        # 按状态码统计
        status_code_result = await self.db.execute(
            select(ExceptionLog.status_code, func.count(ExceptionLog.id).label("count"))
            .where(ExceptionLog.created_at >= cutoff_time)
            .group_by(ExceptionLog.status_code)
            .order_by(desc("count"))
        )
        by_status_code = {
            row.status_code: row.count for row in status_code_result if row.status_code
        }

        # 按用户统计
        user_result = await self.db.execute(
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

