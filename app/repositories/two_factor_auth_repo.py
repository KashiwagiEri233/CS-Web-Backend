"""双因素认证仓储。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.two_factor_auth import TwoFactorAuth


class TwoFactorAuthRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, user_id: int) -> Optional[TwoFactorAuth]:
        return await self.db.get(TwoFactorAuth, user_id)

    async def upsert_pending(
        self, user_id: int, secret_encrypted: str, backup_codes: list
    ) -> TwoFactorAuth:
        """初始化/重置 2FA：写入新 secret 与备用码，回到未启用状态。"""
        record = await self.get(user_id)
        if record is None:
            record = TwoFactorAuth(
                user_id=user_id,
                secret_encrypted=secret_encrypted,
                backup_codes=backup_codes,
                enabled=False,
            )
            self.db.add(record)
        else:
            record.secret_encrypted = secret_encrypted
            record.backup_codes = backup_codes
            record.enabled = False
            record.enabled_at = None
            record.updated_at = now_utc()
        await self.db.flush()
        return record

    async def enable(self, record: TwoFactorAuth) -> None:
        record.enabled = True
        record.enabled_at = now_utc()
        record.updated_at = now_utc()

    async def set_backup_codes(self, record: TwoFactorAuth, backup_codes: list) -> None:
        record.backup_codes = backup_codes
        record.updated_at = now_utc()

    async def delete(self, user_id: int) -> None:
        record = await self.get(user_id)
        if record is not None:
            await self.db.delete(record)
