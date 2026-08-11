"""社区分类服务（ER-15 Phase 4：从 community_service 拆出分类域）。

- 分类 CRUD（含 slug 冲突校验）与列表
- 反范式计数 ``post_count`` 由 PostService 侧维护（adjust_category_count），本服务不直接写

API 契约不变（api/v1/community.py + admin_community.py 端点 path/method/响应结构保持）。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    ErrorCode,
    NotFoundException,
)
from app.repositories.community_repo import CommunityCategoryRepository


class CategoryService:
    """社区分类（categories）服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.category_repo = CommunityCategoryRepository(db)

    async def list_categories(self) -> list:
        return await self.category_repo.list_all()

    async def get_category(self, category_id: int):
        obj = await self.category_repo.get_by_id(category_id)
        if obj is None:
            raise NotFoundException(
                message="分类不存在",
                resource_type="community_category",
                resource_id=str(category_id),
            )
        return obj

    async def create_category(
        self,
        admin_id: int,
        slug: str,
        name: str,
        description=None,
        icon=None,
        sort_order=0,
    ):
        if await self.category_repo.get_by_slug(slug):
            raise ConflictException(
                message="slug 已存在", error_code=ErrorCode.Community.SLUG_EXISTS
            )
        obj = await self.category_repo.create(
            {
                "slug": slug,
                "name": name,
                "description": description,
                "icon": icon,
                "sort_order": sort_order,
                "created_by": admin_id,
            }
        )
        await self.db.commit()
        return obj

    async def update_category(
        self,
        admin_id: int,
        category_id: int,
        slug: str,
        name: str,
        description: Optional[str],
        icon: Optional[str],
        sort_order: int,
    ):
        obj = await self.get_category(category_id)
        if slug and slug != obj.slug:
            if await self.category_repo.get_by_slug(slug):
                raise ConflictException(
                    message="slug 已存在", error_code=ErrorCode.Community.SLUG_EXISTS
                )
        await self.category_repo.update(
            obj,
            {
                "slug": slug,
                "name": name,
                "description": description,
                "icon": icon,
                "sort_order": sort_order,
            },
        )
        await self.db.commit()
        return obj

    async def delete_category(self, admin_id: int, category_id: int) -> None:
        if not await self.category_repo.delete(category_id):
            raise NotFoundException(
                message="分类不存在",
                resource_type="community_category",
                resource_id=str(category_id),
            )
        await self.db.commit()
