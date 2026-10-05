"""Agent 每日简报仓储（AG-P3-03）。"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_briefing import AgentDailyBriefing


class AgentBriefingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_date(
        self, user_id: int, brief_date: date
    ) -> Optional[AgentDailyBriefing]:
        stmt = select(AgentDailyBriefing).where(
            AgentDailyBriefing.user_id == user_id,
            AgentDailyBriefing.brief_date == brief_date,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def create(self, data: dict) -> AgentDailyBriefing:
        obj = AgentDailyBriefing(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj
