"""drop legacy forum_* / blog_posts / blog_likes tables (Phase 6 cleanup)

⚠️ 风险操作 — 需团队评审后执行：
旧表（forum_topics / forum_posts / forum_post_likes / forum_post_tags /
forum_post_views / blog_posts / blog_likes 等）曾作为「数据迁移源」保留于库中，
不参与任何 ORM 建模，也不被应用读写（见 app/models/community.py 注释）。
数据迁移（Phase 1~5）完成后，确认业务数据已从旧表零丢失迁移到 community v2
统一表，方可执行本迁移彻底清理旧表。

执行前建议先预览 SQL 并备份：
    alembic upgrade 22232b182a66c --sql     # 仅打印 SQL，不执行
    pg_dump ... > pre_drop_backup.sql        # 备份

本迁移为**独立可选维护迁移**（down_revision=None，不串入主链），
如暂不清理，请勿 upgrade 到本 revision；主链 head 仍为 22232b182a66b（搜索 GIN）。

Revision ID: 22232b182a66c
Revises:
Create Date: 2026-08-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "22232b182a66c"
down_revision: Union[str, Sequence[str], None] = None  # 独立可选维护迁移，不串入主链
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 旧表清单（仅 DROP 已确认无应用依赖的迁移源表）
LEGACY_TABLES = (
    "forum_topics",
    "forum_posts",
    "forum_post_likes",
    "forum_post_tags",
    "forum_post_views",
    "blog_posts",
    "blog_likes",
)


def upgrade() -> None:
    # 仅 DROP 真实存在的旧表，避免 NOTICE 报错
    for table in LEGACY_TABLES:
        op.execute(
            sa.text(f"DROP TABLE IF EXISTS {table} CASCADE")
        )


def downgrade() -> None:
    # 已彻底删除的旧表无法自动恢复；降级需从备份还原。
    # 此处不执行任何 CREATE，便于 operator 从 pre_drop_backup.sql 恢复。
    raise RuntimeError(
        "不可逆迁移：旧表已 DROP。如需恢复，请从 pre_drop_backup.sql 还原，"
        "不要使用 alembic downgrade。"
    )
