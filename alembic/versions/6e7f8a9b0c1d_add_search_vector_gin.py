"""add search_vector GIN full-text search (Phase 6)

论坛帖 community_posts 与用户 users 增加全文检索向量 search_vector，
由 PostgreSQL 触发器（tsvector_update_trigger, pg_catalog.simple）在写入/更新时自动维护，
并建立 GIN 索引加速 websearch_to_tsquery 查询。历史数据在 upgrade 中回填。

Revision ID: 6e7f8a9b0c1d
Revises: 9f1c2a3b4d5e
Create Date: 2026-08-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6e7f8a9b0c1d"
down_revision: Union[str, Sequence[str], None] = "9f1c2a3b4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- community_posts ----
    op.add_column(
        "community_posts",
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
    )
    op.create_index(
        "ix_community_posts_search_vector",
        "community_posts",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )
    op.execute(
        "CREATE TRIGGER tsvector_update_community_posts "
        "BEFORE INSERT OR UPDATE ON community_posts "
        "FOR EACH ROW EXECUTE FUNCTION "
        "tsvector_update_trigger("
        "search_vector, 'pg_catalog.simple', title, content_markdown"
        ")"
    )
    # 回填历史数据
    op.execute(
        "UPDATE community_posts SET search_vector = "
        "to_tsvector('pg_catalog.simple', "
        "coalesce(title, '') || ' ' || coalesce(content_markdown, ''))"
    )

    # ---- users ----
    op.add_column(
        "users",
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
    )
    op.create_index(
        "ix_users_search_vector",
        "users",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )
    op.execute(
        "CREATE TRIGGER tsvector_update_users "
        "BEFORE INSERT OR UPDATE ON users "
        "FOR EACH ROW EXECUTE FUNCTION "
        "tsvector_update_trigger("
        "search_vector, 'pg_catalog.simple', display_name, username"
        ")"
    )
    # 回填历史数据
    op.execute(
        "UPDATE users SET search_vector = "
        "to_tsvector('pg_catalog.simple', "
        "coalesce(display_name, '') || ' ' || coalesce(username, ''))"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tsvector_update_users ON users")
    op.drop_index("ix_users_search_vector", table_name="users", postgresql_using="gin")
    op.drop_column("users", "search_vector")

    op.execute(
        "DROP TRIGGER IF EXISTS tsvector_update_community_posts ON community_posts"
    )
    op.drop_index(
        "ix_community_posts_search_vector",
        table_name="community_posts",
        postgresql_using="gin",
    )
    op.drop_column("community_posts", "search_vector")
