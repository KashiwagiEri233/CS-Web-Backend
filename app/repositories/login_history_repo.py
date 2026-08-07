"""登录历史仓储。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.login_history import LoginHistory
from app.repositories.base import dml_rowcount


class LoginHistoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        user_id: Optional[int],
        ip: Optional[str],
        user_agent: Optional[str],
        success: bool,
        attempted_email: Optional[str] = None,
    ) -> LoginHistory:
        """记录一次登录尝试。调用方负责 commit。"""
        entry = LoginHistory(
            user_id=user_id,
            ip=ip,
            user_agent=user_agent,
            success=success,
            attempted_email=attempted_email,
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def list_for_user(
        self, user_id: int, *, limit: int = 20
    ) -> list[LoginHistory]:
        """最近登录记录（含失败），按时间倒序。"""
        stmt = (
            select(LoginHistory)
            .where(LoginHistory.user_id == user_id)
            .order_by(LoginHistory.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_failures_for_email(
        self, email: str, *, limit: int = 20
    ) -> list[LoginHistory]:
        """某邮箱的失败登录记录（撞库检测用，user_id 为空）。"""
        stmt = (
            select(LoginHistory)
            .where(
                LoginHistory.attempted_email == email,
                LoginHistory.success.is_(False),
            )
            .order_by(LoginHistory.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def purge_before(self, before: datetime) -> int:
        """批量删除早于指定时间的记录，返回删除行数。调用方负责 commit。"""
        result = await self.db.execute(
            delete(LoginHistory).where(LoginHistory.created_at < before)
        )
        return dml_rowcount(result)
