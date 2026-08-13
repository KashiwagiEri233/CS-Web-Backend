"""add community v2 unified tables

上游重构（2026-08 前端拉取）：论坛 + 博客合并为 community_* 统一表。
新增：community_categories / community_posts / community_comments /
community_reactions / community_favorites / community_post_views /
community_mentions / community_follows / community_reports。
旧表（forum_* / blog_posts / blog_likes）保留作数据迁移源，后续 Phase 6 清理。

Revision ID: 5c6d7e8f9a0b
Revises: 7e8f9a0b1c2d
Create Date: 2026-08-03

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5c6d7e8f9a0b"
down_revision: Union[str, Sequence[str], None] = "7e8f9a0b1c2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "community_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(length=100), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("post_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_community_categories_created_by_users",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug", name="uq_community_categories_slug"),
    )
    op.create_index(
        "ix_community_categories_sort_order",
        "community_categories",
        ["sort_order"],
        unique=False,
    )

    op.create_table(
        "community_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey(
                "community_categories.id",
                name="fk_community_posts_category_id_community_categories",
                ondelete="CASCADE",
            ),
            nullable=True,
        ),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_community_posts_author_id_users",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), nullable=False),
        sa.Column("is_featured", sa.Boolean(), nullable=False),
        sa.Column("reply_count", sa.Integer(), nullable=False),
        sa.Column("favorite_count", sa.Integer(), nullable=False),
        sa.Column("last_reply_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reply_id", sa.Integer(), nullable=True),
        sa.Column(
            "hidden_by",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_community_posts_hidden_by_users",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_reason", sa.Text(), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("cover_image", sa.String(length=1024), nullable=True),
        sa.Column("tags", _JSONB, nullable=True),
        sa.Column(
            "series_id",
            sa.Integer(),
            sa.ForeignKey(
                "blog_series.id",
                name="fk_community_posts_series_id_blog_series",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("series_order", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False),
        sa.Column("like_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug", name="uq_community_posts_slug"),
    )
    op.create_index(
        "idx_community_posts_kind", "community_posts", ["kind"], unique=False
    )
    op.create_index(
        "idx_community_posts_category_id",
        "community_posts",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        "idx_community_posts_status", "community_posts", ["status"], unique=False
    )
    op.create_index(
        "idx_community_posts_author_id", "community_posts", ["author_id"], unique=False
    )
    op.create_index(
        "idx_community_posts_last_reply_at",
        "community_posts",
        ["last_reply_at"],
        unique=False,
    )
    op.create_index(
        "idx_community_posts_is_pinned", "community_posts", ["is_pinned"], unique=False
    )
    op.create_index(
        "idx_community_posts_published_at",
        "community_posts",
        ["published_at"],
        unique=False,
    )
    op.create_index(
        "idx_community_posts_series_id", "community_posts", ["series_id"], unique=False
    )

    op.create_table(
        "community_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "post_id",
            sa.Integer(),
            sa.ForeignKey(
                "community_posts.id",
                name="fk_community_comments_post_id_community_posts",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_community_comments_author_id_users",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "parent_comment_id",
            sa.Integer(),
            sa.ForeignKey(
                "community_comments.id",
                name="fk_community_comments_parent_comment_id_community_comments",
                ondelete="CASCADE",
            ),
            nullable=True,
        ),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("like_count", sa.Integer(), nullable=False),
        sa.Column("reply_count", sa.Integer(), nullable=False),
        sa.Column(
            "hidden_by",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_community_comments_hidden_by_users",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_community_comments_post_id",
        "community_comments",
        ["post_id"],
        unique=False,
    )
    op.create_index(
        "idx_community_comments_parent_comment_id",
        "community_comments",
        ["parent_comment_id"],
        unique=False,
    )
    op.create_index(
        "idx_community_comments_author_id",
        "community_comments",
        ["author_id"],
        unique=False,
    )
    op.create_index(
        "idx_community_comments_status", "community_comments", ["status"], unique=False
    )

    op.create_table(
        "community_reactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_community_reactions_user_id_users",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "target_type", "target_id", name="ux_community_reactions_unique"
        ),
    )
    op.create_index(
        "idx_community_reactions_target",
        "community_reactions",
        ["target_type", "target_id"],
        unique=False,
    )
    op.create_index(
        "idx_community_reactions_user_id",
        "community_reactions",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "community_favorites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_community_favorites_user_id_users",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "target_type", "target_id", name="ux_community_favorites_unique"
        ),
    )
    op.create_index(
        "idx_community_favorites_user_id",
        "community_favorites",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "idx_community_favorites_target",
        "community_favorites",
        ["target_type", "target_id"],
        unique=False,
    )

    op.create_table(
        "community_post_views",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "post_id",
            sa.Integer(),
            sa.ForeignKey(
                "community_posts.id",
                name="fk_community_post_views_post_id_community_posts",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_community_post_views_user_id_users",
                ondelete="CASCADE",
            ),
            nullable=True,
        ),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_community_post_views_post_id",
        "community_post_views",
        ["post_id"],
        unique=False,
    )
    op.create_index(
        "idx_community_post_views_unique_user",
        "community_post_views",
        ["post_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "idx_community_post_views_unique_ip",
        "community_post_views",
        ["post_id", "ip_hash"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )

    op.create_table(
        "community_mentions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "mentioned_user_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_community_mentions_mentioned_user_id_users",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column(
            "source_author_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_community_mentions_source_author_id_users",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("is_notified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_community_mentions_mentioned_user_id",
        "community_mentions",
        ["mentioned_user_id"],
        unique=False,
    )
    op.create_index(
        "idx_community_mentions_is_notified",
        "community_mentions",
        ["is_notified"],
        unique=False,
    )

    op.create_table(
        "community_follows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "follower_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_community_follows_follower_id_users",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "following_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_community_follows_following_id_users",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "follower_id", "following_id", name="ux_community_follows_unique"
        ),
    )
    op.create_index(
        "idx_community_follows_follower",
        "community_follows",
        ["follower_id"],
        unique=False,
    )
    op.create_index(
        "idx_community_follows_following",
        "community_follows",
        ["following_id"],
        unique=False,
    )

    op.create_table(
        "community_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reporter_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_community_reports_reporter_id_users",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "handled_by",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                name="fk_community_reports_handled_by_users",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_community_reports_status", "community_reports", ["status"], unique=False
    )
    op.create_index(
        "idx_community_reports_target",
        "community_reports",
        ["target_type", "target_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_community_reports_target", table_name="community_reports")
    op.drop_index("idx_community_reports_status", table_name="community_reports")
    op.drop_table("community_reports")

    op.drop_index("idx_community_follows_following", table_name="community_follows")
    op.drop_index("idx_community_follows_follower", table_name="community_follows")
    op.drop_table("community_follows")

    op.drop_index("idx_community_mentions_is_notified", table_name="community_mentions")
    op.drop_index(
        "idx_community_mentions_mentioned_user_id", table_name="community_mentions"
    )
    op.drop_table("community_mentions")

    op.drop_index(
        "idx_community_post_views_unique_ip", table_name="community_post_views"
    )
    op.drop_index(
        "idx_community_post_views_unique_user", table_name="community_post_views"
    )
    op.drop_index("idx_community_post_views_post_id", table_name="community_post_views")
    op.drop_table("community_post_views")

    op.drop_index("idx_community_favorites_target", table_name="community_favorites")
    op.drop_index("idx_community_favorites_user_id", table_name="community_favorites")
    op.drop_table("community_favorites")

    op.drop_index("idx_community_reactions_user_id", table_name="community_reactions")
    op.drop_index("idx_community_reactions_target", table_name="community_reactions")
    op.drop_table("community_reactions")

    op.drop_index("idx_community_comments_status", table_name="community_comments")
    op.drop_index("idx_community_comments_author_id", table_name="community_comments")
    op.drop_index(
        "idx_community_comments_parent_comment_id", table_name="community_comments"
    )
    op.drop_index("idx_community_comments_post_id", table_name="community_comments")
    op.drop_table("community_comments")

    op.drop_index("idx_community_posts_series_id", table_name="community_posts")
    op.drop_index("idx_community_posts_published_at", table_name="community_posts")
    op.drop_index("idx_community_posts_is_pinned", table_name="community_posts")
    op.drop_index("idx_community_posts_last_reply_at", table_name="community_posts")
    op.drop_index("idx_community_posts_author_id", table_name="community_posts")
    op.drop_index("idx_community_posts_status", table_name="community_posts")
    op.drop_index("idx_community_posts_category_id", table_name="community_posts")
    op.drop_index("idx_community_posts_kind", table_name="community_posts")
    op.drop_table("community_posts")

    op.drop_index(
        "ix_community_categories_sort_order", table_name="community_categories"
    )
    op.drop_table("community_categories")
