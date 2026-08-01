"""全站公告仓储。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Announcement


class AnnouncementRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active(self, now: datetime) -> list[Announcement]:
        """生效中的公告：is_active + 未过期，按 priority 降序、创建时间降序。"""
        stmt = (
            select(Announcement)
            .where(
                Announcement.is_active.is_(True),
                (Announcement.expires_at.is_(None)) | (Announcement.expires_at > now),
            )
            .order_by(Announcement.priority.desc(), Announcement.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self) -> list[Announcement]:
        stmt = select(Announcement).order_by(Announcement.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, announcement_id: int) -> Optional[Announcement]:
        return await self.db.get(Announcement, announcement_id)

    async def create(self, data: dict) -> Announcement:
        obj = Announcement(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def delete(self, announcement_id: int) -> bool:
        obj = await self.get_by_id(announcement_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True
