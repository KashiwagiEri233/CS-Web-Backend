"""组件注册表服务：items / variants / guides。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, ErrorCode, NotFoundException
from app.models.component_registry import ComponentRegistryItem
from app.repositories.tools_repo import ComponentRegistryRepository
from app.schemas.tools import (
    ComponentGuideInput,
    ComponentItemInput,
    ComponentVariantInput,
)


class ComponentRegistryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ComponentRegistryRepository(db)

    async def list_components(self) -> list[dict]:
        items = await self.repo.list_items()
        result = []
        for item in items:
            result.append(await self._to_out(item))
        return result

    async def get_component(self, item_id: int) -> dict:
        item = await self.repo.get_item(item_id)
        if item is None:
            raise NotFoundException(
                message="组件不存在",
                resource_type="component_registry_item",
                resource_id=str(item_id),
            )
        return await self._to_out(item)

    async def create_component(self, data: ComponentItemInput) -> dict:
        if await self.repo.get_item_by_slug(data.slug):
            raise ConflictException(
                message="slug 已存在", error_code=ErrorCode.Conflict.SLUG_EXISTS
            )
        item = await self.repo.create_item(data.model_dump())
        await self.db.commit()
        return await self._to_out(item)

    async def update_component(self, item_id: int, data: ComponentItemInput) -> dict:
        item = await self.repo.get_item(item_id)
        if item is None:
            raise NotFoundException(
                message="组件不存在",
                resource_type="component_registry_item",
                resource_id=str(item_id),
            )
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(item, key, value)
        await self.db.commit()
        return await self._to_out(item)

    async def delete_component(self, item_id: int) -> None:
        if not await self.repo.delete_item(item_id):
            raise NotFoundException(
                message="组件不存在",
                resource_type="component_registry_item",
                resource_id=str(item_id),
            )
        await self.db.commit()

    async def replace_variants(
        self, item_id: int, variants: list[ComponentVariantInput]
    ) -> dict:
        await self.get_component(item_id)
        await self.repo.replace_variants(item_id, [v.model_dump() for v in variants])
        await self.db.commit()
        return await self.get_component(item_id)

    async def toggle_variant(
        self, item_id: int, variant_id: int, enabled: bool
    ) -> dict:
        variant = await self.repo.get_variant(item_id, variant_id)
        if variant is None:
            raise NotFoundException(
                message="变体不存在",
                resource_type="component_registry_variant",
                resource_id=str(variant_id),
            )
        await self.repo.toggle_variant(variant_id, enabled)
        await self.db.commit()
        return await self.get_component(item_id)

    async def update_guide(self, item_id: int, data: ComponentGuideInput) -> dict:
        await self.get_component(item_id)
        await self.repo.upsert_guide(item_id, data.use_cases, data.anti_patterns)
        await self.db.commit()
        return await self.get_component(item_id)

    async def _to_out(self, item: ComponentRegistryItem) -> dict:
        variants = await self.repo.list_variants(item.id)
        guide = await self.repo.get_guide(item.id)
        return {
            "id": item.id,
            "name": item.name,
            "slug": item.slug,
            "category": item.category,
            "description": item.description,
            "migration_status": item.migration_status,
            "sort_order": item.sort_order,
            "variants": [
                {
                    "id": v.id,
                    "size": v.size,
                    "color": v.color,
                    "state": v.state,
                    "is_enabled": v.is_enabled,
                }
                for v in variants
            ],
            "guide": (
                {
                    "id": guide.id,
                    "use_cases": guide.use_cases or [],
                    "anti_patterns": guide.anti_patterns or [],
                }
                if guide
                else None
            ),
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
