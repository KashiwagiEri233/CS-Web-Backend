"""组件注册表模型：前端组件库注册（items / variants / guides 三表）。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime as _DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class ComponentRegistryItem(Base):
    """组件注册条目：slug 唯一；migration_status 标记迁移状态。"""

    __tablename__ = "component_registry_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, default="general", index=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    migration_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="legacy", index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=now_utc,
        onupdate=now_utc,
    )

    def __repr__(self) -> str:
        return f"<ComponentRegistryItem(id={self.id}, slug='{self.slug}')>"


class ComponentRegistryVariant(Base):
    """组件变体：(item_id, size, color, state) 唯一，防止重复。"""

    __tablename__ = "component_registry_variants"

    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "size",
            "color",
            "state",
            name="ux_component_registry_variants_unique",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("component_registry_items.id"), nullable=False, index=True
    )
    size: Mapped[str] = mapped_column(String(50), nullable=False)
    color: Mapped[str] = mapped_column(String(50), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    def __repr__(self) -> str:
        return f"<ComponentRegistryVariant(id={self.id}, item_id={self.item_id})>"


class ComponentRegistryGuide(Base):
    """组件使用指南：与 item 1:1（item_id 唯一）。"""

    __tablename__ = "component_registry_guides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("component_registry_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # use_cases / anti_patterns：JSON 数组文本
    use_cases: Mapped[Optional[list]] = mapped_column(
        JSONDict, nullable=True, default=list
    )
    anti_patterns: Mapped[Optional[list]] = mapped_column(
        JSONDict, nullable=True, default=list
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=now_utc,
        onupdate=now_utc,
    )

    def __repr__(self) -> str:
        return f"<ComponentRegistryGuide(id={self.id}, item_id={self.item_id})>"
