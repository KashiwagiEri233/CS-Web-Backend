"""
异常告警仓储层
提供异常告警的数据库操作方法
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exception_log import ExceptionAlert


class ExceptionAlertRepository:
    """异常告警仓储"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_alert(self, alert_data: Dict[str, Any]) -> ExceptionAlert:
        """
        创建异常告警

        Args:
            alert_data: 告警数据

        Returns:
            创建的告警对象
        """
        alert = ExceptionAlert(**alert_data)
        self.db.add(alert)
        await self.db.commit()
        await self.db.refresh(alert)
        return alert

    async def get_alert_by_id(self, alert_id: int) -> Optional[ExceptionAlert]:
        """
        通过ID获取异常告警

        Args:
            alert_id: 告警ID

        Returns:
            告警对象或None
        """
        result = await self.db.execute(
            select(ExceptionAlert).where(ExceptionAlert.id == alert_id)
        )
        return result.scalar_one_or_none()

    async def get_alert_by_alert_id(self, alert_id: str) -> Optional[ExceptionAlert]:
        """
        通过告警ID获取异常告警

        Args:
            alert_id: 告警ID

        Returns:
            告警对象或None
        """
        result = await self.db.execute(
            select(ExceptionAlert).where(ExceptionAlert.alert_id == alert_id)
        )
        return result.scalar_one_or_none()

    async def get_open_alerts(self) -> List[ExceptionAlert]:
        """
        获取所有开放的异常告警

        Returns:
            开放告警列表
        """
        result = await self.db.execute(
            select(ExceptionAlert).where(ExceptionAlert.status == "open")
        )
        return list(result.scalars().all())

    async def acknowledge_alert(
        self, alert_id: int, acknowledged_by: str
    ) -> Optional[ExceptionAlert]:
        """
        确认异常告警

        Args:
            alert_id: 告警ID
            acknowledged_by: 确认人

        Returns:
            更新后的告警对象或None
        """
        result = await self.db.execute(
            select(ExceptionAlert).where(ExceptionAlert.id == alert_id)
        )
        alert = result.scalar_one_or_none()

        if not alert:
            return None

        alert.status = "acknowledged"
        alert.acknowledged_by = acknowledged_by
        alert.acknowledged_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(alert)
        return alert

    async def resolve_alert(
        self, alert_id: int, resolved_by: str
    ) -> Optional[ExceptionAlert]:
        """
        解决异常告警

        Args:
            alert_id: 告警ID
            resolved_by: 解决人

        Returns:
            更新后的告警对象或None
        """
        result = await self.db.execute(
            select(ExceptionAlert).where(ExceptionAlert.id == alert_id)
        )
        alert = result.scalar_one_or_none()

        if not alert:
            return None

        alert.status = "resolved"
        alert.resolved_by = resolved_by
        alert.resolved_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(alert)
        return alert
