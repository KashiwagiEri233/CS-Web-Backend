"""add user password_changed_at

Revision ID: a7c3e91f2b04
Revises: 36bbae24c38c
Create Date: 2026-07-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c3e91f2b04"
down_revision: Union[str, Sequence[str], None] = "36bbae24c38c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为 users 表增加 password_changed_at（改密后吊销旧 access token）。"""
    op.add_column(
        "users",
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
