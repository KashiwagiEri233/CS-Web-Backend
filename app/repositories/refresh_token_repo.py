from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.refresh_token import RefreshToken


def _now() -> datetime:
    return now_utc()


class RefreshTokenRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        user_id: int,
        token_hash: str,
        family_id: str,
        expires_at: datetime,
    ) -> RefreshToken:
        """持久化一条 refresh token 记录。调用方负责 commit。"""
        rt = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=expires_at,
        )
        self.db.add(rt)
        await self.db.flush()
        return rt

    async def get_by_hash(self, token_hash: str) -> Optional[RefreshToken]:
        """通过 token 哈希获取记录。"""
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke(self, token_id: int) -> None:
        """软撤销单条。调用方负责 commit。"""
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id)
            .values(revoked_at=_now())
        )

    async def revoke_family(self, family_id: str) -> int:
        """撤销整个 family（检测到复用时批量失效）。返回受影响行数。"""
        result = await self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=_now())
        )
        return result.rowcount or 0

    async def revoke_all_for_user(self, user_id: int) -> int:
        """撤销该用户全部 refresh token（改密/封禁时使用）。"""
        result = await self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=_now())
        )
        return result.rowcount or 0
