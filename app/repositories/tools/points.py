"""积分仓储。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.points import PointsTransaction


class PointsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def last_balance(self, user_id: int) -> int:
        stmt = (
            select(PointsTransaction.balance_after)
            .where(PointsTransaction.user_id == user_id)
            .order_by(PointsTransaction.created_at.desc(), PointsTransaction.id.desc())
            .limit(1)
        )
        value = (await self.db.execute(stmt)).scalar_one_or_none()
        return int(value or 0)

    async def create_transaction(
        self,
        *,
        user_id: int,
        amount: int,
        reason: str,
        source_type: str,
        source_id,
        balance_after: int,
    ) -> PointsTransaction:
        obj = PointsTransaction(
            user_id=user_id,
            amount=amount,
            reason=reason,
            source_type=source_type,
            source_id=source_id,
            balance_after=balance_after,
        )
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def list_transactions(
        self, user_id: int, limit: int = 50, skip: int = 0
    ) -> list[PointsTransaction]:
        stmt = (
            select(PointsTransaction)
            .where(PointsTransaction.user_id == user_id)
            .order_by(PointsTransaction.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def leaderboard(self, top_n: int = 20) -> list[tuple[int, int]]:
        """(user_id, balance) 按余额倒序。"""
        subq = (
            select(
                PointsTransaction.user_id,
                func.max(PointsTransaction.balance_after).label("balance"),
            )
            .group_by(PointsTransaction.user_id)
            .subquery()
        )
        stmt = (
            select(subq.c.user_id, subq.c.balance)
            .order_by(subq.c.balance.desc())
            .limit(top_n)
        )
        rows = await self.db.execute(stmt)
        return [(int(uid), int(balance)) for uid, balance in rows.all()]
