"""社区举报仓储。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.community import CommunityReport
from app.repositories.base import paginate


class CommunityReportRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(
        self, *, status: Optional[str] = None, skip: int = 0, limit: int = 20
    ) -> tuple[list[CommunityReport], int]:
        conditions = []
        if status:
            conditions.append(CommunityReport.status == status)
        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(CommunityReport).where(*conditions)
                )
            ).scalar_one()
        )
        stmt = paginate(
            select(CommunityReport)
            .where(*conditions)
            .order_by(CommunityReport.created_at.desc()),
            skip,
            limit,
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_by_id(self, report_id: int) -> Optional[CommunityReport]:
        return await self.db.get(CommunityReport, report_id)

    async def create(self, data: dict) -> CommunityReport:
        obj = CommunityReport(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def resolve(
        self, report: CommunityReport, handled_by: int, status: str
    ) -> None:
        report.status = status
        report.handled_by = handled_by
        report.handled_at = now_utc()
