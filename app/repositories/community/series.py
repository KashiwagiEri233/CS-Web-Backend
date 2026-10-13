"""社区系列仓储。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.community_series import CommunitySeries


class CommunitySeriesRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[CommunitySeries]:
        stmt = select(CommunitySeries).order_by(CommunitySeries.created_at.desc())
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def get_by_id(self, series_id: int) -> Optional[CommunitySeries]:
        return await self.db.get(CommunitySeries, series_id)

    async def slug_exists(self, slug: str) -> bool:
        stmt = select(CommunitySeries.id).where(CommunitySeries.slug == slug).limit(1)
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none() is not None

    async def create(self, data: dict) -> CommunitySeries:
        obj = CommunitySeries(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def delete(self, series_id: int) -> bool:
        obj = await self.get_by_id(series_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True