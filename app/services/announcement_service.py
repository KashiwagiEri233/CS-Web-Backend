"""公告服务：公开读取（状态 + 可见范围 + 角色定向）+ 管理员 CRUD / 发布归档。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.core.timezone import now_utc
from app.models.notification import Announcement
from app.models.organization import MemberProfile
from app.models.user import User
from app.repositories.announcement_repo import AnnouncementRepository
from app.repositories.organization_repo import OrganizationRepository
from app.schemas.announcement import AnnouncementInput


class AnnouncementService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AnnouncementRepository(db)
        self.org_repo = OrganizationRepository(db)

    # ------------------------------------------------------------------ 公开

    async def list_active(
        self, *, user: Optional[User] = None, roles: Optional[list[str]] = None
    ) -> list[Announcement]:
        """生效公告：published + 未过期 + 可见范围 + 角色定向。"""
        items = await self.repo.list_active(now_utc())
        member = None
        if user is not None:
            member = await self.org_repo.get_member_by_user_id(user.id)
            if member is not None and member.membership_status != "active":
                member = None
        return [
            a
            for a in items
            if self._visible(a, member)
            and (
                not a.target_roles
                or (roles and any(r in a.target_roles for r in roles))
            )
        ]

    @staticmethod
    def _visible(announcement: Announcement, member: Optional[MemberProfile]) -> bool:
        if announcement.visibility == "public":
            return True
        if member is None:
            return False
        if announcement.visibility == "members":
            return True
        if announcement.visibility == "peak":
            return (
                announcement.peak_id is not None
                and member.peak_id == announcement.peak_id
            )
        return False

    # ------------------------------------------------------------------ 管理

    async def list_all(self, created_by: Optional[int] = None) -> list[Announcement]:
        return await self.repo.list_all(created_by=created_by)

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
        payload["status"] = data.status or (
            "published" if data.is_active else "draft"
        )
        payload["is_active"] = payload["status"] == "published"
        if payload["status"] == "published":
            payload["published_at"] = now_utc()
        obj = await self.repo.create(payload)
        await self.db.commit()
        return obj

    async def update(
        self, announcement_id: int, data: AnnouncementInput
    ) -> Announcement:
        obj = await self.get(announcement_id)
        changes = data.model_dump(exclude_unset=True)
        if "status" in changes and changes["status"] is not None:
            obj.status = changes["status"]
            obj.is_active = obj.status == "published"
            if obj.status == "published" and obj.published_at is None:
                obj.published_at = now_utc()
        elif "is_active" in changes:
            obj.status = "published" if changes["is_active"] else "archived"
            obj.is_active = bool(changes["is_active"])
            if obj.status == "published" and obj.published_at is None:
                obj.published_at = now_utc()
        for key, value in changes.items():
            if key in {"status", "is_active"}:
                continue
            setattr(obj, key, value)
        obj.version = (obj.version or 1) + 1
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
        if obj.status == "published":
            obj.status = "archived"
            obj.is_active = False
        else:
            obj.status = "published"
            obj.is_active = True
            obj.published_at = obj.published_at or now_utc()
        obj.version = (obj.version or 1) + 1
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def publish(self, announcement_id: int) -> Announcement:
        obj = await self.get(announcement_id)
        obj.status = "published"
        obj.is_active = True
        obj.published_at = now_utc()
        obj.version = (obj.version or 1) + 1
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def archive(self, announcement_id: int) -> Announcement:
        obj = await self.get(announcement_id)
        obj.status = "archived"
        obj.is_active = False
        obj.version = (obj.version or 1) + 1
        await self.db.commit()
        await self.db.refresh(obj)
        return obj
