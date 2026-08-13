"""rename blog_series -> community_series (blog 命名彻底清除，统一为社区)

Phase 7 重命名：社区「系列」实体的物理表名由 blog_series 重命名为
community_series，与 ORM 模型 `app/models/community_series.py` 的
`__tablename__ = "community_series"` 对齐，彻底清除代码库中 blog 命名痕迹。

本迁移为可逆的 ALTER TABLE ... RENAME（低风险），但若需降级请在生产环境
DB_AUTO_MIGRATE=False 时谨慎执行：
    alembic upgrade 2a3b4c5d6e7f --sql   # 预览 SQL
    alembic downgrade 4f5a6b7c8d9e       # 还原表名

Revision ID: 2a3b4c5d6e7f
Revises: 4f5a6b7c8d9e
Create Date: 2026-08-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2a3b4c5d6e7f"
down_revision: Union[str, Sequence[str], None] = "4f5a6b7c8d9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 仅当旧表存在时改名，避免重复执行报错
    op.execute(
        sa.text(
            "ALTER TABLE IF EXISTS blog_series RENAME TO community_series"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE IF EXISTS community_series RENAME TO blog_series"
        )
    )
