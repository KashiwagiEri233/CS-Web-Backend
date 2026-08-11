"""社区系列服务（ER-15 Phase 4：从 community_service 拆出系列域）。

- 系列 CRUD / 列表；slug 唯一化（_unique_series_slug）

API 契约不变（api/v1/community.py 端点 path/method/响应结构保持）。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import COMMUNITY_LIMITS
from app.core.exceptions import (
    AuthorizationException,
    ErrorCode,
    NotFoundException,
)
from app.repositories.community_repo import CommunitySeriesRepository
from app.services.community_utils import generate_slug


class SeriesService:
    """社区系列（series）服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.series_repo = CommunitySeriesRepository(db)

    async def list_series(self) -> list:
        return await self.series_repo.list_all()

    async def create_series(self, user_id: int, title: str, description: Optional[str]):
        slug = await self._unique_series_slug(generate_slug(title))
        series = await self.series_repo.create(
            {
                "title": title,
                "description": description,
                "slug": slug,
                "created_by": user_id,
            }
        )
        await self.db.commit()
        return series

    async def delete_series(self, user_id: int, series_id: int, is_admin: bool) -> None:
        series = await self.series_repo.get_by_id(series_id)
        if series is None:
            raise NotFoundException(
                message="系列不存在",
                resource_type="community_series",
                resource_id=str(series_id),
            )
        if user_id != series.created_by and not is_admin:
            raise AuthorizationException(
                message="无权删除该系列",
                error_code=ErrorCode.Authorization.PERMISSION_DENIED,
            )
        await self.series_repo.delete(series_id)
        await self.db.commit()

    # ------------------------------------------------------------------ 内部

    async def _unique_series_slug(self, base: str) -> str:
        slug = base
        suffix = 2
        while await self.series_repo.slug_exists(slug):
            slug = f"{base[: COMMUNITY_LIMITS['SLUG_MAX'] - 3]}-{suffix}"
            suffix += 1
        return slug
