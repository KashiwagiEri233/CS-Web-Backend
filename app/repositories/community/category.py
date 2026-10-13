"""社区分类仓储。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.community import CommunityCategory


class CommunityCategoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[CommunityCategory]:
        stmt = select(CommunityCategory).order_by(
            CommunityCategory.sort_order.asc(), CommunityCategory.id.asc()
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def get_by_id(self, category_id: int) -> Optional[CommunityCategory]:
        return await self.db.get(CommunityCategory, category_id)

    async def get_by_slug(self, slug: str) -> Optional[CommunityCategory]:
        stmt = select(CommunityCategory).where(CommunityCategory.slug == slug)
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def create(self, data: dict) -> CommunityCategory:
        obj = CommunityCategory(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, category: CommunityCategory, data: dict) -> None:
        for key, value in data.items():
            setattr(category, key, value)

    async def delete(self, category_id: int) -> bool:
        obj = await self.get_by_id(category_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True