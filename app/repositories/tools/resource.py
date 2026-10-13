"""资源仓储。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resource import Resource
from app.core.query_helpers import jsonb_contains
from app.repositories.base import paginate


class ResourceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_resources(
        self,
        *,
        status: Optional[str] = None,
        resource_type: Optional[str] = None,
        tag: Optional[str] = None,
        submitted_by: Optional[int] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Resource], int]:
        conditions = []
        if status:
            conditions.append(Resource.status == status)
        if resource_type:
            conditions.append(Resource.resource_type == resource_type)
        if tag and tag.strip():
            # 2026-08-10 修复：Resource.tech_tags 为 JSON().with_variant(JSONB())（Variant），
            # contains 退化成字符串 LIKE 且实际调用报错；type_coerce(JSONB) 走 @> 包含。
            conditions.append(jsonb_contains(Resource.tech_tags, [tag.strip()]))
        if submitted_by:
            conditions.append(Resource.submitted_by == submitted_by)
        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(Resource).where(*conditions)
                )
            ).scalar_one()
        )
        stmt = paginate(
            select(Resource).where(*conditions).order_by(Resource.created_at.desc()),
            skip,
            limit,
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all()), total

    async def get_by_id(self, resource_id: int) -> Optional[Resource]:
        return await self.db.get(Resource, resource_id)

    async def create(self, data: dict) -> Resource:
        obj = Resource(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, resource: Resource, data: dict) -> None:
        for key, value in data.items():
            setattr(resource, key, value)

    async def delete(self, resource_id: int) -> bool:
        obj = await self.get_by_id(resource_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True

    async def increment_view(self, resource_id: int) -> None:
        await self.db.execute(
            update(Resource)
            .where(Resource.id == resource_id)
            .values(view_count=Resource.view_count + 1)
        )