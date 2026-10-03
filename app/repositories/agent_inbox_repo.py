"""Agent 建议收件箱仓储（AG-P3-01）。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_inbox import AgentInboxItem
from app.repositories.base import dml_rowcount


class AgentInboxRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, item_id: int) -> Optional[AgentInboxItem]:
        return await self.db.get(AgentInboxItem, item_id)

    async def find_by_idempotency_key(
        self, user_id: int, idempotency_key: str
    ) -> Optional[AgentInboxItem]:
        stmt = select(AgentInboxItem).where(
            AgentInboxItem.user_id == user_id,
            AgentInboxItem.idempotency_key == idempotency_key,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def create(self, data: dict) -> AgentInboxItem:
        obj = AgentInboxItem(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def list_for_user(
        self,
        user_id: int,
        *,
        status: Optional[str] = None,
        type: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[AgentInboxItem], int]:
        """用户收件箱列表（已处理项默认排除由 status=None 时过滤）+ 总数。"""
        base = select(AgentInboxItem).where(AgentInboxItem.user_id == user_id)
        if status is not None:
            base = base.where(AgentInboxItem.status == status)
        if type is not None:
            base = base.where(AgentInboxItem.type == type)
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        stmt = base.order_by(AgentInboxItem.created_at.desc()).offset(skip).limit(limit)
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, int(total)

    async def promote_due_snoozes(self, user_id: int, now: datetime) -> int:
        """snoozed 且到期 → pending（读路径惰性回收；AG-P3-06 后移 arq 定时）。"""
        stmt = (
            update(AgentInboxItem)
            .where(
                AgentInboxItem.user_id == user_id,
                AgentInboxItem.status == "snoozed",
                AgentInboxItem.snoozed_until.is_not(None),
                AgentInboxItem.snoozed_until <= now,
            )
            .values(status="pending", snoozed_until=None, updated_at=now)
        )
        result = await self.db.execute(stmt)
        return dml_rowcount(result)

    async def expire_stale(self, user_id: int, now: datetime) -> int:
        """pending 且已过期 → expired（同上，惰性回收）。"""
        stmt = (
            update(AgentInboxItem)
            .where(
                AgentInboxItem.user_id == user_id,
                AgentInboxItem.status == "pending",
                AgentInboxItem.expires_at.is_not(None),
                AgentInboxItem.expires_at <= now,
            )
            .values(status="expired", updated_at=now)
        )
        result = await self.db.execute(stmt)
        return dml_rowcount(result)
