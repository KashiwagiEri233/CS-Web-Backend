"""站内通知仓储。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.repositories.base import dml_rowcount


class NotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        user_id: int,
        type: str,
        title: str,
        content: Optional[str],
        sender_id: Optional[int],
    ) -> Notification:
        obj = Notification(
            user_id=user_id,
            type=type,
            title=title,
            content=content,
            sender_id=sender_id,
        )
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def create_for_all(
        self,
        *,
        type: str,
        title: str,
        content: Optional[str],
        sender_id: Optional[int],
        user_ids: list[int],
    ) -> int:
        """向指定用户批量创建通知（广播）。返回创建条数。"""
        if not user_ids:
            return 0
        self.db.add_all(
            [
                Notification(
                    user_id=uid,
                    type=type,
                    title=title,
                    content=content,
                    sender_id=sender_id,
                )
                for uid in user_ids
            ]
        )
        await self.db.flush()
        return len(user_ids)

    async def list_for_user(
        self,
        user_id: int,
        *,
        is_read: Optional[bool] = None,
        type: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Notification], int]:
        """分页查询用户通知（新→旧），返回 (列表, 总数)。"""
        conditions = [Notification.user_id == user_id]
        if is_read is not None:
            conditions.append(Notification.is_read.is_(is_read))
        if type is not None:
            conditions.append(Notification.type == type)

        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(Notification).where(*conditions)
                )
            ).scalar_one()
        )
        stmt = (
            select(Notification)
            .where(*conditions)
            .order_by(Notification.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def get_owned(
        self, user_id: int, notification_id: int
    ) -> Optional[Notification]:
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_read(self, notification_id: int) -> None:
        await self.db.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(is_read=True)
        )

    async def mark_all_read(self, user_id: int) -> int:
        result = await self.db.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True)
        )
        return dml_rowcount(result)

    async def unread_count(self, user_id: int) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(Notification)
                    .where(
                        Notification.user_id == user_id,
                        Notification.is_read.is_(False),
                    )
                )
            ).scalar_one()
        )

    async def list_recent_broadcasts(self, limit: int = 20) -> list[dict]:
        """最近群发记录（按 title/content/type 去重聚合，含接收人数）。"""
        limit = min(max(1, limit), 100)
        rows = (
            await self.db.execute(
                select(
                    Notification.title,
                    Notification.content,
                    Notification.type,
                    func.max(Notification.created_at).label("created_at"),
                    func.count().label("cnt"),
                )
                .where(Notification.sender_id.is_not(None))
                .group_by(Notification.title, Notification.content, Notification.type)
                .order_by(func.max(Notification.created_at).desc())
                .limit(limit)
            )
        ).all()
        return [
            {
                "title": r.title,
                "content": r.content,
                "type": (
                    r.type if r.type in {"system", "admin", "activity"} else "system"
                ),
                "created_at": r.created_at,
                "cnt": r.cnt,
            }
            for r in rows
        ]
