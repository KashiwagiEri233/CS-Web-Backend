"""历史密码仓储。"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.password_history import PasswordHistory


class PasswordHistoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user_id: int, password_hash: str) -> PasswordHistory:
        """记录一条历史密码。调用方负责 commit。"""
        entry = PasswordHistory(user_id=user_id, password_hash=password_hash)
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def recent_hashes(self, user_id: int, limit: int) -> list[str]:
        """最近 N 条历史密码哈希（新→旧）。"""
        if limit <= 0:
            return []
        stmt = (
            select(PasswordHistory.password_hash)
            .where(PasswordHistory.user_id == user_id)
            .order_by(PasswordHistory.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def prune(self, user_id: int, keep: int) -> None:
        """清理超出保留上限 2 倍的旧记录，避免表无限膨胀。"""
        if keep <= 0:
            return
        keep_count = keep * 2
        subq = (
            select(PasswordHistory.id)
            .where(PasswordHistory.user_id == user_id)
            .order_by(PasswordHistory.created_at.desc())
            .limit(keep_count)
        )
        await self.db.execute(
            delete(PasswordHistory).where(
                PasswordHistory.user_id == user_id,
                PasswordHistory.id.not_in(subq),
            )
        )
