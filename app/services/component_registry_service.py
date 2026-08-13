"""组件注册表服务：items / variants / guides。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    ErrorCode,
    NotFoundException,
    ValidationException,
)
from app.models.component_registry import ComponentRegistryItem
from app.repositories.tools_repo import ComponentRegistryRepository
from app.schemas.tools import (
    ComponentGuideInput,
    ComponentItemInput,
    ComponentItemOut,
    ComponentVariantInput,
    ComponentVariantOut,
)
from app.schemas.feature_visibility import VisibilityRule
from app.services.feature_visibility_service import (
    KNOWN_MODULE_KEYS,
    FeatureVisibilityService,
)


@dataclass
class MigrationStatusResult:
    """set_migration_status 的轻量返回：携带旧状态供治理事件审计。"""

    name: str
    old_migration_status: str
    migration_status: str
    # 当迁移置为 done（migrated）时自动开放了对应的可见性模块，标记为 True，
    # 供治理事件审计与前端联动展示。
    visibility_opened: bool = False
    # 组件 slug 映射到的可见性 module_key（slug↔key 闭环的键），便于前端/审计追溯。
    visibility_key: str = ""


# 变体矩阵预设合法值（前端 VARIANT_PRESETS 保持一致）。
VARIANT_PRESETS = {"all", "none", "primary", "minimal"}

# 标记「迁移完成」的状态值；达到该状态即自动开放对应可见性模块。
MIGRATION_DONE_STATUS = "migrated"


def slug_to_visibility_key(slug: str) -> str:
    """slug↔key 闭环：组件注册表 slug 到可见性 module_key 的稳定映射约定。

    组件注册表以原子组件（slug 如 ``button``）为粒度，可见性体系以功能模块
    （``tool-*`` 形态或 ``tools`` 等）为粒度，两者前缀不同。映射规则：

    - 若 ``slug`` 本身就是已注册的可见性模块键（如 ``tools``），则直接命中；
    - 否则约定组件 ``<slug>`` 对应可见性模块 ``tool-<slug>``。

    这样「迁移 done → 自动开放可见性」既有明确目标，又兼容历史原子组件数据。
    """
    if slug in KNOWN_MODULE_KEYS:
        return slug
    return f"tool-{slug}"


class ComponentRegistryService:
    def __init__(
        self,
        db: AsyncSession,
        visibility: "FeatureVisibilityService | None" = None,
    ):
        self.db = db
        self.repo = ComponentRegistryRepository(db)
        # slug↔key 闭环：注入可见性服务以联动开放；允许为 None（纯单测场景）。
        self.visibility = visibility

    async def list_components(self) -> list[ComponentItemOut]:
        items = await self.repo.list_items()
        result = []
        for item in items:
            result.append(await self._to_out(item))
        return result

    async def get_component(self, item_id: int) -> ComponentItemOut:
        item = await self.repo.get_item(item_id)
        if item is None:
            raise NotFoundException(
                message="组件不存在",
                resource_type="component_registry_item",
                resource_id=str(item_id),
            )
        return await self._to_out(item)

    async def create_component(self, data: ComponentItemInput) -> ComponentItemOut:
        if await self.repo.get_item_by_slug(data.slug):
            raise ConflictException(
                message="slug 已存在", error_code=ErrorCode.Community.SLUG_EXISTS
            )
        item = await self.repo.create_item(data.model_dump())
        await self.db.commit()
        return await self._to_out(item)

    async def update_component(
        self, item_id: int, data: ComponentItemInput
    ) -> ComponentItemOut:
        item = await self.repo.get_item(item_id)
        if item is None:
            raise NotFoundException(
                message="组件不存在",
                resource_type="component_registry_item",
                resource_id=str(item_id),
            )
        payload = data.model_dump(exclude_unset=True)
        if "slug" in payload and payload["slug"] != item.slug:
            if await self.repo.get_item_by_slug(payload["slug"]):
                raise ConflictException(
                    message="slug 已存在", error_code=ErrorCode.Community.SLUG_EXISTS
                )
        # slug↔key 闭环：slug 本身即映射约定（tool-<slug>），无需强制属于已知键，
        # 以兼容历史原子组件数据（button/input/...）。
        for key, value in payload.items():
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
    ) -> list[ComponentVariantOut]:
        # 轻量出口：仅校验 item 存在 + 该变体归属正确，回传该 item 的最新变体列表，
        # 避免 toggle_variant 走全量 get_component（多查一次 guide），降低高频开关的查询开销。
        item = await self.get_component(item_id)
        variant = await self.repo.get_variant(item_id, variant_id)
        if variant is None:
            raise NotFoundException(
                message="变体不存在",
                resource_type="component_registry_variant",
                resource_id=str(variant_id),
            )
        await self.repo.toggle_variant(variant_id, enabled)
        await self.db.commit()
        return [
            ComponentVariantOut.model_validate(
                {
                    "id": v.id,
                    "size": v.size,
                    "color": v.color,
                    "state": v.state,
                    "is_enabled": v.is_enabled,
                }
            )
            for v in await self.repo.list_variants(item.id)
        ]

    async def update_guide(
        self, item_id: int, data: ComponentGuideInput
    ) -> ComponentItemOut:
        await self.get_component(item_id)
        await self.repo.upsert_guide(item_id, data.use_cases, data.anti_patterns)
        await self.db.commit()
        return await self.get_component(item_id)

    async def set_migration_status(
        self, item_id: int, migration_status: str
    ) -> "MigrationStatusResult":
        item = await self.repo.get_item(item_id)
        if item is None:
            raise NotFoundException(
                message="组件不存在",
                resource_type="component_registry_item",
                resource_id=str(item_id),
            )
        old_status = item.migration_status
        if old_status == migration_status:
            return MigrationStatusResult(
                name=item.name,
                old_migration_status=old_status,
                migration_status=old_status,
            )
        item.migration_status = migration_status
        # 可见性闭环：迁移达到 done（migrated）时，自动开放对应 slug 的可见性模块，
        # 使组件在「迁移完成」后立刻对所有角色可见。仅在注入可见性服务时生效。
        visibility_key = slug_to_visibility_key(item.slug)
        visibility_opened = False
        if (
            migration_status == MIGRATION_DONE_STATUS
            and old_status != MIGRATION_DONE_STATUS
            and self.visibility is not None
        ):
            # 仅当映射出的可见性模块已注册时才开放，避免污染未登记的键。
            # （现有原子组件 slug 尚无对应 tool-* 键，将安全跳过而不报错。）
            old_rule = await self.visibility.get_rule(visibility_key)
            if old_rule is not None and not (
                old_rule.guest and old_rule.member and old_rule.admin
            ):
                await self.visibility.update_module(
                    visibility_key, VisibilityRule(guest=True, member=True, admin=True)
                )
                visibility_opened = True
        await self.db.commit()
        return MigrationStatusResult(
            name=item.name,
            old_migration_status=old_status,
            migration_status=item.migration_status,
            visibility_opened=visibility_opened,
            visibility_key=visibility_key,
        )

    async def apply_variant_preset(
        self, item_id: int, preset: str
    ) -> list[ComponentVariantOut]:
        if preset not in VARIANT_PRESETS:
            raise ValidationException(message="变体预设无效")
        # 校验 item 存在（同时拿到 name 供审计）
        item = await self.get_component(item_id)
        if not item.variants:
            return []
        variants = await self.repo.apply_variant_preset(item_id, preset)
        return [
            ComponentVariantOut.model_validate(
                {
                    "id": v.id,
                    "size": v.size,
                    "color": v.color,
                    "state": v.state,
                    "is_enabled": v.is_enabled,
                }
            )
            for v in variants
        ]

    async def _to_out(self, item: ComponentRegistryItem) -> ComponentItemOut:
        variants = await self.repo.list_variants(item.id)
        guide = await self.repo.get_guide(item.id)
        # 可见性闭环：附带 slug 对应可见性模块（tool-<slug>）当前是否全开，供前端联动展示。
        visibility_open = None
        if self.visibility is not None:
            rule = await self.visibility.get_rule(slug_to_visibility_key(item.slug))
            if rule is not None:
                visibility_open = rule.guest and rule.member and rule.admin
        return ComponentItemOut.model_validate(
            {
                "id": item.id,
                "name": item.name,
                "slug": item.slug,
                "category": item.category,
                "description": item.description,
                "migration_status": item.migration_status,
                "sort_order": item.sort_order,
                "visibility_open": visibility_open,
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
        )
