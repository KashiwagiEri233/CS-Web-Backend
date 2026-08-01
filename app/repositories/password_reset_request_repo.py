"""密码重置申请仓储。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.password_reset_request import PasswordResetRequest


class PasswordResetRequestRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, email: str) -> PasswordResetRequest:
        req = PasswordResetRequest(email=email)
        self.db.add(req)
        await self.db.flush()
        return req

    async def get_pending_for_email(self, email: str) -> Optional[PasswordResetRequest]:
        stmt = (
            select(PasswordResetRequest)
            .where(
                PasswordResetRequest.email == email,
                PasswordResetRequest.status == "pending",
            )
            .order_by(PasswordResetRequest.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, request_id: int) -> Optional[PasswordResetRequest]:
        return await self.db.get(PasswordResetRequest, request_id)

    async def list(self, status: Optional[str] = None) -> list[PasswordResetRequest]:
        stmt = select(PasswordResetRequest).order_by(
            PasswordResetRequest.created_at.desc()
        )
        if status:
            stmt = stmt.where(PasswordResetRequest.status == status)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def resolve(
        self,
        request: PasswordResetRequest,
        *,
        status: str,
        admin_id: Optional[int],
        admin_note: Optional[str],
    ) -> None:
        request.status = status
        request.admin_id = admin_id
        request.admin_note = admin_note
        request.resolved_at = now_utc()
