"""邮箱验证码仓储。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.verification_code import VerificationCode
from app.repositories.base import dml_rowcount


class VerificationCodeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def invalidate_for_email(self, email: str) -> None:
        """把该邮箱全部未消费验证码标记为已用（发新码前调用）。"""
        await self.db.execute(
            update(VerificationCode)
            .where(
                VerificationCode.email == email,
                VerificationCode.used.is_(False),
            )
            .values(used=True)
        )

    async def create(
        self, email: str, code_hash: str, expires_at: datetime
    ) -> VerificationCode:
        """创建验证码记录。调用方负责 commit。"""
        vc = VerificationCode(email=email, code_hash=code_hash, expires_at=expires_at)
        self.db.add(vc)
        await self.db.flush()
        return vc

    async def get_latest_unused(
        self, email: str, now: datetime
    ) -> Optional[VerificationCode]:
        """获取该邮箱最新一条未消费且未过期的验证码。"""
        stmt = (
            select(VerificationCode)
            .where(
                VerificationCode.email == email,
                VerificationCode.used.is_(False),
                VerificationCode.expires_at > now,
            )
            .order_by(VerificationCode.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_used(self, code_id: int) -> None:
        await self.db.execute(
            update(VerificationCode)
            .where(VerificationCode.id == code_id)
            .values(used=True)
        )

    async def purge_expired(self, now: datetime) -> int:
        """物理删除全部过期验证码。返回删除行数。"""
        result = await self.db.execute(
            delete(VerificationCode).where(VerificationCode.expires_at < now)
        )
        return dml_rowcount(result)
