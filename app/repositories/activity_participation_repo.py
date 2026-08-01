"""用户主页活动参与记录仓储。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import ActivityParticipation


class ActivityParticipationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_user(self, user_id: int) -> list[ActivityParticipation]:
        """用户活动参与记录，按活动日期倒序。"""
        stmt = (
            select(ActivityParticipation)
            .where(ActivityParticipation.user_id == user_id)
            .order_by(ActivityParticipation.activity_date.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
