"""add role admin display fields

子阶段 2.5（admin 聚合）：roles 表增加展示字段，对齐前端角色管理 UI。

Revision ID: h2i3j4k5l6m7
Revises: f6a7b8c9d0e1
Create Date: 2026-08-01

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "h2i3j4k5l6m7"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "roles", sa.Column("display_name", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "roles",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("roles", "is_system", server_default=None)
    op.add_column(
        "roles",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("roles", "sort_order", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("roles", "sort_order")
    op.drop_column("roles", "is_system")
    op.drop_column("roles", "display_name")
