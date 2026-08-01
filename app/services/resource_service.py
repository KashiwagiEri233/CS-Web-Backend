"""资源服务：提交 / 审核 / 浏览 / 上传。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.resource import Resource
from app.models.user import User
from app.repositories.tools_repo import ResourceRepository
from app.schemas.tools import ResourceInput


class ResourceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ResourceRepository(db)

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
        resources, total = await self.repo.list_resources(
            status=status,
            resource_type=resource_type,
            tag=tag,
            submitted_by=submitted_by,
            skip=skip,
            limit=limit,
        )
        await self._load_submitter_names(resources)
        return resources, total

    async def get_resource(self, resource_id: int) -> Resource:
        resource = await self.repo.get_by_id(resource_id)
        if resource is None:
            raise NotFoundException(
                message="资源不存在",
                resource_type="resource",
                resource_id=str(resource_id),
            )
        await self._load_submitter_names([resource])
        return resource

    async def create_resource(self, submitted_by: int, data: ResourceInput) -> Resource:
        payload = data.model_dump()
        payload["submitted_by"] = submitted_by
        payload["status"] = "pending"
        resource = await self.repo.create(payload)
        await self.db.commit()
        return resource

    async def update_resource(self, resource_id: int, data: ResourceInput) -> Resource:
        resource = await self.get_resource(resource_id)
        await self.repo.update(resource, data.model_dump(exclude_unset=True))
        await self.db.commit()
        return resource

    async def review_resource(
        self, reviewed_by: int, resource_id: int, approved: bool, note: Optional[str]
    ) -> Resource:
        resource = await self.get_resource(resource_id)
        await self.repo.update(
            resource,
            {
                "status": "approved" if approved else "rejected",
                "reviewed_by": reviewed_by,
                "review_note": note,
            },
        )
        await self.db.commit()
        return resource

    async def delete_resource(self, resource_id: int) -> None:
        if not await self.repo.delete(resource_id):
            raise NotFoundException(
                message="资源不存在",
                resource_type="resource",
                resource_id=str(resource_id),
            )
        await self.db.commit()

    async def increment_view(self, resource_id: int) -> None:
        await self.repo.increment_view(resource_id)
        await self.db.commit()

    async def _load_submitter_names(self, resources: list[Resource]) -> None:
        if not resources:
            return
        user_ids = {r.submitted_by for r in resources}
        users = {
            u.id: u
            for u in (await self.db.execute(select(User).where(User.id.in_(user_ids))))
            .scalars()
            .all()
        }
        for resource in resources:
            user = users.get(resource.submitted_by)
            setattr(
                resource,
                "submitted_by_name",
                (user.display_name or user.username) if user else None,
            )
