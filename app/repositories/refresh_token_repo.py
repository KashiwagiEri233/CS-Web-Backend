from datetime import datetime
from typing import Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.refresh_token import RefreshToken
from app.core.constants import TOKEN_PURGE_BATCH_SIZE
from app.repositories.base import dml_rowcount


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
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> RefreshToken:
        """持久化一条 refresh token 记录。调用方负责 commit。"""
        rt = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.add(rt)
        await self.db.flush()
        return rt

    async def get_by_hash(
        self, token_hash: str, *, for_update: bool = False
    ) -> Optional[RefreshToken]:
        """通过 token 哈希获取记录；轮换时可加行锁串行化并发请求。"""
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke(self, token_id: int) -> None:
        """软撤销单条。调用方负责 commit。"""
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id)
            .values(revoked_at=_now())
        )

    async def family_has_active(self, family_id: str) -> bool:
        """family 内是否仍有未撤销且未过期的 token。

        用于轮换宽限判定：仅当 family 仍有活跃后继 token 时，已撤销 token 的
        再次出现才按并发重试放行；整体撤销（revoke_all）后无活跃 token，按复用处置。
        """
        now = _now()
        stmt = select(func.count(RefreshToken.id)).where(
            RefreshToken.family_id == family_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        result = await self.db.execute(stmt)
        return (result.scalar() or 0) > 0

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
        return dml_rowcount(result)

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
        return dml_rowcount(result)

    async def list_active_for_user(self, user_id: int) -> list[RefreshToken]:
        """列出该用户未撤销且未过期的 refresh token（设备列表，新→旧）。"""
        now = _now()
        stmt = (
            select(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .order_by(RefreshToken.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def revoke_by_id_for_user(self, token_id: int, user_id: int) -> bool:
        """撤销指定 refresh token（须属于该用户）。返回是否命中。"""
        result = await self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.id == token_id,
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=_now())
        )
        return dml_rowcount(result) > 0

    async def purge_expired(self, *, batch_size: int = TOKEN_PURGE_BATCH_SIZE) -> int:
        """分批物理删除已过期 refresh 行，返回删除行数。

        已撤销但尚未自然过期的记录必须保留，用于 rotation 复用检测。
        """
        now = _now()
        ids = (
            select(RefreshToken.id)
            .where(RefreshToken.expires_at < now)
            .order_by(RefreshToken.id)
            .limit(batch_size)
        )
        stmt = delete(RefreshToken).where(RefreshToken.id.in_(ids))
        result = await self.db.execute(stmt)
        return dml_rowcount(result)
