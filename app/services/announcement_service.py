"""公告服务：公开读取（生效过滤 + 角色定向）+ 管理员 CRUD。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.core.timezone import now_utc
from app.models.notification import Announcement
from app.repositories.announcement_repo import AnnouncementRepository
from app.schemas.announcement import AnnouncementInput


class AnnouncementService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AnnouncementRepository(db)

    # ------------------------------------------------------------------ 公开

    async def list_active(
        self, roles: Optional[list[str]] = None
    ) -> list[Announcement]:
        """生效公告（is_active + 未过期），按角色定向过滤。"""
        items = await self.repo.list_active(now_utc())
        return [
            a
            for a in items
            if not a.target_roles or (roles and any(r in a.target_roles for r in roles))
        ]

    # ------------------------------------------------------------------ 管理

    async def list_all(self) -> list[Announcement]:
        return await self.repo.list_all()

    async def get(self, announcement_id: int) -> Announcement:
        obj = await self.repo.get_by_id(announcement_id)
        if obj is None:
            raise NotFoundException(
                message="公告不存在",
                resource_type="announcement",
                resource_id=str(announcement_id),
            )
        return obj

    async def create(self, created_by: int, data: AnnouncementInput) -> Announcement:
        payload = data.model_dump()
        payload["created_by"] = created_by
        obj = await self.repo.create(payload)
        await self.db.commit()
        return obj

    async def update(
        self, announcement_id: int, data: AnnouncementInput
    ) -> Announcement:
        obj = await self.get(announcement_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def delete(self, announcement_id: int) -> None:
        if not await self.repo.delete(announcement_id):
            raise NotFoundException(
                message="公告不存在",
                resource_type="announcement",
                resource_id=str(announcement_id),
            )
        await self.db.commit()

    async def toggle_active(self, announcement_id: int) -> Announcement:
        obj = await self.get(announcement_id)
        obj.is_active = not obj.is_active
        await self.db.commit()
        await self.db.refresh(obj)
        return obj
