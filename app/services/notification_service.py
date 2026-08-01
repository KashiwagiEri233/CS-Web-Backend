"""站内通知服务：查询/已读管理 + 创建（供事件订阅与业务模块调用）。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.notification import Notification
from app.repositories.notification_repo import NotificationRepository
from app.repositories.user_repo import UserRepository


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = NotificationRepository(db)

    # ------------------------------------------------------------------ 查询

    async def list_for_user(
        self,
        user_id: int,
        *,
        is_read: Optional[bool] = None,
        type: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Notification], int]:
        return await self.repo.list_for_user(
            user_id, is_read=is_read, type=type, skip=skip, limit=limit
        )

    async def unread_count(self, user_id: int) -> int:
        return await self.repo.unread_count(user_id)

    async def list_recent_broadcasts(self, limit: int = 20) -> list[dict]:
        """最近群发记录（管理员视图）。"""
        return await self.repo.list_recent_broadcasts(limit)

    async def mark_read(self, user_id: int, notification_id: int) -> None:
        obj = await self.repo.get_owned(user_id, notification_id)
        if obj is None:
            raise NotFoundException(
                message="通知不存在",
                resource_type="notification",
                resource_id=str(notification_id),
            )
        await self.repo.mark_read(notification_id)
        await self.db.commit()

    async def mark_all_read(self, user_id: int) -> int:
        n = await self.repo.mark_all_read(user_id)
        await self.db.commit()
        return n

    # ------------------------------------------------------------------ 创建

    async def create(
        self,
        *,
        user_id: int,
        type: str,
        title: str,
        content: Optional[str] = None,
        sender_id: Optional[int] = None,
        commit: bool = True,
    ) -> Notification:
        obj = await self.repo.create(
            user_id=user_id,
            type=type,
            title=title,
            content=content,
            sender_id=sender_id,
        )
        if commit:
            await self.db.commit()
        return obj

    async def broadcast(
        self,
        *,
        title: str,
        content: Optional[str] = None,
        sender_id: Optional[int] = None,
        user_ids: Optional[list[int]] = None,
    ) -> int:
        """全站通知：user_ids 为空时广播给全部活跃用户。"""
        if user_ids is None:
            user_repo = UserRepository(self.db)
            user_ids = [u.id for u in await user_repo.list_active()]
        if not user_ids:
            return 0
        n = await self.repo.create_for_all(
            type="admin",
            title=title,
            content=content,
            sender_id=sender_id,
            user_ids=user_ids,
        )
        await self.db.commit()
        return n
