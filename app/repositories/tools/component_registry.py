"""组件注册表仓储。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.component_registry import (
    ComponentRegistryGuide,
    ComponentRegistryItem,
    ComponentRegistryVariant,
)
from app.repositories.base import dml_rowcount


class ComponentRegistryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_items(self) -> list[ComponentRegistryItem]:
        stmt = select(ComponentRegistryItem).order_by(
            ComponentRegistryItem.sort_order.asc(), ComponentRegistryItem.id.asc()
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def get_item(self, item_id: int) -> Optional[ComponentRegistryItem]:
        return await self.db.get(ComponentRegistryItem, item_id)

    async def get_item_by_slug(self, slug: str) -> Optional[ComponentRegistryItem]:
        stmt = select(ComponentRegistryItem).where(ComponentRegistryItem.slug == slug)
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def create_item(self, data: dict) -> ComponentRegistryItem:
        obj = ComponentRegistryItem(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def delete_item(self, item_id: int) -> bool:
        obj = await self.get_item(item_id)
        if obj is None:
            return False
        await self.db.delete(obj)
        return True

    async def list_variants(self, item_id: int) -> list[ComponentRegistryVariant]:
        stmt = (
            select(ComponentRegistryVariant)
            .where(ComponentRegistryVariant.item_id == item_id)
            .order_by(ComponentRegistryVariant.id.asc())
            # 批量 update/upsert 后强制从 DB 重新读取，避免 identity-map 缓存旧值。
            .execution_options(populate_existing=True)
        )
        rows = await self.db.execute(stmt)
        return list(rows.scalars().all())

    async def get_variant(
        self, item_id: int, variant_id: int
    ) -> Optional[ComponentRegistryVariant]:
        stmt = select(ComponentRegistryVariant).where(
            ComponentRegistryVariant.id == variant_id,
            ComponentRegistryVariant.item_id == item_id,
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def replace_variants(self, item_id: int, variants: list[dict]) -> None:
        # 先整体禁用该 item 所有变体，保留主键稳定（避免前端列表 key 抖动）。
        await self.db.execute(
            update(ComponentRegistryVariant)
            .where(ComponentRegistryVariant.item_id == item_id)
            .values(is_enabled=False)
        )
        if not variants:
            await self.db.flush()
            return
        # 批量 upsert：以 (item_id, size, color, state) 唯一约束为冲突键，
        # 已存在的行更新 is_enabled，不存在的行插入。一次语句完成，避免逐条 SELECT+UPDATE 的 N 次查询。
        stmt = postgresql.insert(ComponentRegistryVariant).values(
            [
                {
                    "item_id": item_id,
                    "size": v.get("size", ""),
                    "color": v.get("color", ""),
                    "state": v.get("state", ""),
                    "is_enabled": bool(v.get("is_enabled", True)),
                }
                for v in variants
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["item_id", "size", "color", "state"],
            set_={"is_enabled": stmt.excluded.is_enabled},
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def toggle_variant(self, variant_id: int, enabled: bool) -> bool:
        result = await self.db.execute(
            update(ComponentRegistryVariant)
            .where(ComponentRegistryVariant.id == variant_id)
            .values(is_enabled=enabled)
        )
        return dml_rowcount(result) > 0

    async def apply_variant_preset(
        self, item_id: int, preset: str
    ) -> list[ComponentRegistryVariant]:
        """应用变体矩阵预设：按 preset 规则计算各变体的 is_enabled，复用批量 upsert 写回。

        不增删变体，仅翻转 is_enabled；矩阵维度来自已存在的变体集合。
        """
        variants = await self.list_variants(item_id)
        if not variants:
            return []
        updated = [
            {
                "size": v.size,
                "color": v.color,
                "state": v.state,
                "is_enabled": _preset_enabled(preset, v.size, v.color, v.state),
            }
            for v in variants
        ]
        await self.replace_variants(item_id, updated)
        return await self.list_variants(item_id)

    async def get_guide(self, item_id: int) -> Optional[ComponentRegistryGuide]:
        stmt = select(ComponentRegistryGuide).where(
            ComponentRegistryGuide.item_id == item_id
        )
        rows = await self.db.execute(stmt)
        return rows.scalar_one_or_none()

    async def upsert_guide(
        self, item_id: int, use_cases: list, anti_patterns: list
    ) -> ComponentRegistryGuide:
        guide = await self.get_guide(item_id)
        if guide is None:
            guide = ComponentRegistryGuide(
                item_id=item_id, use_cases=use_cases, anti_patterns=anti_patterns
            )
            self.db.add(guide)
        else:
            guide.use_cases = use_cases
            guide.anti_patterns = anti_patterns
            guide.updated_at = now_utc()
        await self.db.flush()
        return guide


def _preset_enabled(preset: str, size: str, color: str, state: str) -> bool:
    """预设规则：基于 size/color/state 计算单个变体是否启用。"""
    if preset == "all":
        return True
    if preset == "none":
        return False
    if preset == "primary":
        # 仅主色启用，其余关闭
        return color == "primary"
    if preset == "minimal":
        # 最小可用集：主色 + 默认态 + 中号
        return color == "primary" and state == "default" and size == "md"
    # 未知预设：保持原样（交给上层校验，这里兜底为启用）
    return True