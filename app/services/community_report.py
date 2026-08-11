"""社区举报服务（ER-15 Phase 4：从 community_service 拆出举报域）。

- 举报提交（post/comment 目标校验）/ 列表 / 处理（resolve/dismiss）

API 契约不变（api/v1/community.py + admin_community.py 端点 path/method/响应结构保持）。
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.community import CommunityReport
from app.repositories.community_repo import (
    CommunityCommentRepository,
    CommunityPostRepository,
    CommunityReportRepository,
)


class ReportService:
    """社区举报（reports）服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.report_repo = CommunityReportRepository(db)
        self.post_repo = CommunityPostRepository(db)
        self.comment_repo = CommunityCommentRepository(db)

    async def submit_report(
        self,
        reporter_id: int,
        target_type: str,
        target_id: int,
        reason: str,
        detail: Optional[str],
    ) -> CommunityReport:
        if target_type == "post":
            report_target: Any = await self.post_repo.get_by_id(target_id)
        else:
            report_target = await self.comment_repo.get_by_id(target_id)
        if report_target is None:
            raise NotFoundException(
                message="目标不存在",
                resource_type=f"community_{target_type}",
                resource_id=str(target_id),
            )
        report = await self.report_repo.create(
            {
                "reporter_id": reporter_id,
                "target_type": target_type,
                "target_id": target_id,
                "reason": reason,
                "detail": detail,
            }
        )
        await self.db.commit()
        return report

    async def list_reports(
        self, *, status: Optional[str] = None, skip: int = 0, limit: int = 20
    ) -> tuple[list[CommunityReport], int]:
        return await self.report_repo.list(status=status, skip=skip, limit=limit)

    async def resolve_report(
        self, admin_id: int, report_id: int, status: str
    ) -> CommunityReport:
        report = await self.report_repo.get_by_id(report_id)
        if report is None:
            raise NotFoundException(
                message="举报不存在",
                resource_type="community_report",
                resource_id=str(report_id),
            )
        await self.report_repo.resolve(report, admin_id, status)
        await self.db.commit()
        return report
