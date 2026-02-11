"""
异常指标仓储层
提供异常指标的数据库操作方法
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exception_log import ExceptionMetrics


class ExceptionMetricsRepository:
    """异常指标仓储"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_metrics(self, metrics_data: Dict[str, Any]) -> ExceptionMetrics:
        """
        创建异常指标

        Args:
            metrics_data: 指标数据

        Returns:
            创建的指标对象
        """
        metrics = ExceptionMetrics(**metrics_data)
        self.db.add(metrics)
        await self.db.commit()
        await self.db.refresh(metrics)
        return metrics

    async def get_metrics_by_time_window(
        self, time_window: str, window_start: datetime, window_end: datetime
    ) -> Optional[ExceptionMetrics]:
        """
        通过时间窗口获取异常指标

        Args:
            time_window: 时间窗口
            window_start: 窗口开始时间
            window_end: 窗口结束时间

        Returns:
            指标对象或None
        """
        result = await self.db.execute(
            select(ExceptionMetrics).where(
                and_(
                    ExceptionMetrics.time_window == time_window,
                    ExceptionMetrics.window_start == window_start,
                    ExceptionMetrics.window_end == window_end,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_metrics(
        self, time_window: str, limit: int = 10
    ) -> List[ExceptionMetrics]:
        """
        获取最新的异常指标

        Args:
            time_window: 时间窗口
            limit: 限制数量

        Returns:
            指标列表
        """
        result = await self.db.execute(
            select(ExceptionMetrics)
            .where(ExceptionMetrics.time_window == time_window)
            .order_by(desc(ExceptionMetrics.window_end))
            .limit(limit)
        )
        return list(result.scalars().all())
