"""add permissions resource action unique constraint

Revision ID: c41e8d7a2f90
Revises: b8d4f02c3e15
Create Date: 2026-07-14 00:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "c41e8d7a2f90"
down_revision: Union[str, Sequence[str], None] = "b8d4f02c3e15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """使数据库约束与 Permission ORM 模型保持一致。"""
    if not context.is_offline_mode():
        duplicates = op.get_bind().execute(sa.text("""
                SELECT resource, action, COUNT(*) AS duplicate_count
                FROM permissions
                GROUP BY resource, action
                HAVING COUNT(*) > 1
                ORDER BY resource, action
                LIMIT 10
                """)).fetchall()
        if duplicates:
            sample = ", ".join(
                f"{resource}:{action} ({count})"
                for resource, action, count in duplicates
            )
            raise RuntimeError(
                "无法创建 permissions(resource, action) 唯一约束；"
                f"请先合并重复权限。示例: {sample}"
            )

    op.create_unique_constraint(
        "uq_permission_resource_action",
        "permissions",
        ["resource", "action"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_permission_resource_action",
        "permissions",
        type_="unique",
    )
