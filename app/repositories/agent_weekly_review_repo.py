"""Agent 每周复盘仓储（AG-P3-04）。"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_weekly_review import AgentWeeklyReview


class AgentWeeklyReviewRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_week(
        self, user_id: int, week_start: date
    ) -> Optional[AgentWeeklyReview]:
        stmt = select(AgentWeeklyReview).where(
            AgentWeeklyReview.user_id == user_id,
            AgentWeeklyReview.week_start == week_start,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def create(self, data: dict) -> AgentWeeklyReview:
        obj = AgentWeeklyReview(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj
