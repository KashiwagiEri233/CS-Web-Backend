"""add on delete cascade to component registry FKs

component_registry_variants.item_id / component_registry_guides.item_id
原 FK 无级联策略（NO ACTION），删除组件时被引用拒绝。改为 ON DELETE CASCADE
（与业务语义一致：变体/指南随组件删除）。

Revision ID: e5f6g7h8i9j0
Revises: c8d9e0f1a2b3
Create Date: 2026-08-03

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6g7h8i9j0"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK_VARIANTS = "fk_component_registry_variants_item_id_component_registry_items"
_FK_GUIDES = "fk_component_registry_guides_item_id_component_registry_items"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(_FK_VARIANTS, "component_registry_variants", type_="foreignkey")
    op.create_foreign_key(
        _FK_VARIANTS,
        "component_registry_variants",
        "component_registry_items",
        ["item_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(_FK_GUIDES, "component_registry_guides", type_="foreignkey")
    op.create_foreign_key(
        _FK_GUIDES,
        "component_registry_guides",
        "component_registry_items",
        ["item_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(_FK_VARIANTS, "component_registry_variants", type_="foreignkey")
    op.create_foreign_key(
        _FK_VARIANTS,
        "component_registry_variants",
        "component_registry_items",
        ["item_id"],
        ["id"],
    )
    op.drop_constraint(_FK_GUIDES, "component_registry_guides", type_="foreignkey")
    op.create_foreign_key(
        _FK_GUIDES,
        "component_registry_guides",
        "component_registry_items",
        ["item_id"],
        ["id"],
    )
