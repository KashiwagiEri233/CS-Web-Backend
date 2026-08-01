"""入社申请仓储。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.join_application import JoinApplication


class JoinApplicationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> JoinApplication:
        obj = JoinApplication(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def list_for_user(self, user_id: int) -> list[JoinApplication]:
        stmt = (
            select(JoinApplication)
            .where(JoinApplication.user_id == user_id)
            .order_by(JoinApplication.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list(self, status: Optional[str] = None) -> list[JoinApplication]:
        stmt = select(JoinApplication).order_by(JoinApplication.created_at.desc())
        if status:
            stmt = stmt.where(JoinApplication.status == status)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, application_id: int) -> Optional[JoinApplication]:
        return await self.db.get(JoinApplication, application_id)

    async def review(
        self,
        application: JoinApplication,
        *,
        status: str,
        reviewed_by: int,
        review_note: Optional[str],
    ) -> None:
        application.status = status
        application.reviewed_by = reviewed_by
        application.review_note = review_note
