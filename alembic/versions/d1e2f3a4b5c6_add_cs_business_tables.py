"""add cs business tables

前后端分离迁移（Phase 0 数据层基线）：将前端 36 张业务表迁移到 PostgreSQL。
- users 表扩展业务资料字段（display_name/bio/avatar/tech_tags 等）
- 新建 35 张表（认证周边 / 系统 / 活动 / 论坛 / 博客 / 通知 / 考试 / 任务 / 积分）

⚠️ 本迁移为离线手写（生成时无可用 PostgreSQL 实例），需在 Linux/有 PG 环境
执行 `alembic upgrade head` 后用 `alembic check` / autogenerate 比对验证，
见 docs/BackDoc-MigV.md。

Revision ID: d1e2f3a4b5c6
Revises: e6a4b91d70c2
Create Date: 2026-08-01

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "e6a4b91d70c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSONB = postgresql.JSONB(astext_type=sa.Text())


def _add_users_business_columns() -> None:
    """扩展 users 表：业务资料字段（迁移自前端 users 表）。"""
    op.add_column(
        "users", sa.Column("display_name", sa.String(length=100), nullable=True)
    )
    op.add_column("users", sa.Column("bio", sa.Text(), nullable=True))
    op.add_column(
        "users", sa.Column("avatar_url", sa.String(length=255), nullable=True)
    )
    # NOT NULL + 默认值两段式：先带 server_default 保证存量行可写，再移除默认对齐元数据
    op.add_column(
        "users",
        sa.Column(
            "avatar_type",
            sa.String(length=20),
            nullable=False,
            server_default="initial",
        ),
    )
    op.alter_column("users", "avatar_type", server_default=None)
    op.add_column(
        "users", sa.Column("github_url", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "users", sa.Column("website_url", sa.String(length=255), nullable=True)
    )
    op.add_column("users", sa.Column("github_id", sa.String(length=50), nullable=True))
    op.add_column("users", sa.Column("tech_tags", _JSONB, nullable=True))
    op.create_index("ix_users_github_id", "users", ["github_id"], unique=True)


def _drop_users_business_columns() -> None:
    """回滚 users 业务字段。"""
    op.drop_index("ix_users_github_id", table_name="users")
    op.drop_column("users", "tech_tags")
    op.drop_column("users", "github_id")
    op.drop_column("users", "website_url")
    op.drop_column("users", "github_url")
    op.drop_column("users", "avatar_type")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "bio")
    op.drop_column("users", "display_name")


def upgrade() -> None:
    """Upgrade schema."""
    _add_users_business_columns()

    # ---- 认证周边 ----
    op.create_table(
        "login_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_login_history_user_id_users"),
            nullable=True,
        ),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("attempted_email", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_login_history_user_id", "login_history", ["user_id"], unique=False
    )
    op.create_index(
        "idx_login_history_user",
        "login_history",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_login_history_attempted_email",
        "login_history",
        ["attempted_email", "created_at"],
        unique=False,
    )

    op.create_table(
        "password_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id", name="fk_password_history_user_id_users", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_password_history_user_id", "password_history", ["user_id"], unique=False
    )
    op.create_index(
        "idx_password_history_user",
        "password_history",
        ["user_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "verification_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=100), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_verification_codes_email", "verification_codes", ["email"], unique=False
    )
    op.create_index(
        "ix_verification_codes_expires_at",
        "verification_codes",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "password_reset_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "admin_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_password_reset_requests_admin_id_users"),
            nullable=True,
        ),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_password_reset_requests_status",
        "password_reset_requests",
        ["status"],
        unique=False,
    )

    op.create_table(
        "two_factor_auth",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id", name="fk_two_factor_auth_user_id_users", ondelete="CASCADE"
            ),
            primary_key=True,
        ),
        sa.Column("secret_encrypted", sa.String(length=1024), nullable=False),
        sa.Column("backup_codes", _JSONB, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ---- 系统 ----
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("module", sa.String(length=50), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("module", "key", name="ux_settings_module_key"),
    )
    op.create_index("ix_settings_module", "settings", ["module"], unique=False)

    op.create_table(
        "resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("tech_tags", _JSONB, nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "submitted_by",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_resources_submitted_by_users"),
            nullable=False,
        ),
        sa.Column(
            "reviewed_by",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_resources_reviewed_by_users"),
            nullable=True,
        ),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("file_url", sa.String(length=1024), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False),
        sa.Column("like_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_resources_resource_type", "resources", ["resource_type"], unique=False
    )
    op.create_index("ix_resources_status", "resources", ["status"], unique=False)
    op.create_index(
        "ix_resources_submitted_by", "resources", ["submitted_by"], unique=False
    )
    op.create_index(
        "ix_resources_created_at", "resources", ["created_at"], unique=False
    )

    op.create_table(
        "component_registry_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("migration_status", sa.String(length=50), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug", name="uq_component_registry_items_slug"),
    )
    op.create_index(
        "ix_component_registry_items_category",
        "component_registry_items",
        ["category"],
        unique=False,
    )
    op.create_index(
        "ix_component_registry_items_migration_status",
        "component_registry_items",
        ["migration_status"],
        unique=False,
    )

    op.create_table(
        "component_registry_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey(
                "component_registry_items.id",
                name="fk_component_registry_variants_item_id_component_registry_items",
            ),
            nullable=False,
        ),
        sa.Column("size", sa.String(length=50), nullable=False),
        sa.Column("color", sa.String(length=50), nullable=False),
        sa.Column("state", sa.String(length=50), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.UniqueConstraint(
            "item_id",
            "size",
            "color",
            "state",
            name="ux_component_registry_variants_unique",
        ),
    )
    op.create_index(
        "ix_component_registry_variants_item_id",
        "component_registry_variants",
        ["item_id"],
        unique=False,
    )

    op.create_table(
        "component_registry_guides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey(
                "component_registry_items.id",
                name="fk_component_registry_guides_item_id_component_registry_items",
            ),
            nullable=False,
        ),
        sa.Column("use_cases", _JSONB, nullable=True),
        sa.Column("anti_patterns", _JSONB, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("item_id", name="uq_component_registry_guides_item_id"),
    )
    op.create_index(
        "ix_component_registry_guides_item_id",
        "component_registry_guides",
        ["item_id"],
        unique=True,
    )

    op.create_table(
        "join_applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("applicant_name", sa.String(length=100), nullable=False),
        sa.Column("student_id", sa.String(length=50), nullable=False),
        sa.Column("major", sa.String(length=100), nullable=False),
        sa.Column("tech_tags", _JSONB, nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("contact_qq", sa.String(length=50), nullable=True),
        sa.Column("contact_phone", sa.String(length=50), nullable=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_join_applications_user_id_users"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "reviewed_by",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_join_applications_reviewed_by_users"),
            nullable=True,
        ),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_join_applications_status", "join_applications", ["status"], unique=False
    )
    op.create_index(
        "ix_join_applications_created_at",
        "join_applications",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_join_applications_user_id", "join_applications", ["user_id"], unique=False
    )

    # ---- 活动 ----
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("month", sa.String(length=20), nullable=True),
        sa.Column("date", sa.String(length=20), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("year", sa.String(length=10), nullable=True),
        sa.Column("topics", _JSONB, nullable=True),
        sa.Column("tags", _JSONB, nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_events_created_by_users"),
            nullable=True,
        ),
        sa.Column("registration_fields", _JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_events_is_pinned", "events", ["is_pinned"], unique=False)
    op.create_index("ix_events_status", "events", ["status"], unique=False)
    op.create_index("ix_events_date", "events", ["date"], unique=False)

    op.create_table(
        "event_registrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_event_registrations_user_id_users"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", name="fk_event_registrations_event_id_events"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("form_data", _JSONB, nullable=True),
        sa.UniqueConstraint(
            "user_id", "event_id", name="ux_event_registrations_unique"
        ),
    )
    op.create_index(
        "ix_event_registrations_user_id",
        "event_registrations",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_event_registrations_event_id",
        "event_registrations",
        ["event_id"],
        unique=False,
    )

    op.create_table(
        "event_checkins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", name="fk_event_checkins_event_id_events"),
            nullable=False,
        ),
        sa.Column(
            "registration_id",
            sa.Integer(),
            sa.ForeignKey(
                "event_registrations.id",
                name="fk_event_checkins_registration_id_event_registrations",
            ),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_event_checkins_user_id_users"),
            nullable=True,
        ),
        sa.Column("checkin_code", sa.String(length=64), nullable=False),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "checked_in_by",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_event_checkins_checked_in_by_users"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "registration_id", name="uq_event_checkins_registration_id"
        ),
    )
    op.create_index(
        "ix_event_checkins_event_id", "event_checkins", ["event_id"], unique=False
    )
    op.create_index(
        "ix_event_checkins_checkin_code",
        "event_checkins",
        ["checkin_code"],
        unique=False,
    )

    op.create_table(
        "activity_participations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_activity_participations_user_id_users"),
            nullable=False,
        ),
        sa.Column("activity_title", sa.String(length=255), nullable=False),
        sa.Column("activity_date", sa.String(length=20), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_activity_participations_user_id",
        "activity_participations",
        ["user_id"],
        unique=False,
    )

    # ---- 论坛 ----
    op.create_table(
        "forum_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(length=100), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("topic_count", sa.Integer(), nullable=False),
        sa.Column("post_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_forum_categories_created_by_users"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug", name="uq_forum_categories_slug"),
    )
    op.create_index(
        "ix_forum_categories_sort_order",
        "forum_categories",
        ["sort_order"],
        unique=False,
    )

    # forum_topics 与 forum_replies 存在循环外键（topics.last_reply_id -> replies.id，
    # replies.topic_id -> topics.id）：先建 topics（last_reply_id 暂不带 FK），
    # 再建 replies，最后 ALTER 补 topics 的外键。
    op.create_table(
        "forum_topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey(
                "forum_categories.id",
                name="fk_forum_topics_category_id_forum_categories",
            ),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_forum_topics_author_id_users"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), nullable=False),
        sa.Column("is_featured", sa.Boolean(), nullable=False),
        sa.Column("view_count", sa.Integer(), nullable=False),
        sa.Column("reply_count", sa.Integer(), nullable=False),
        sa.Column("like_count", sa.Integer(), nullable=False),
        sa.Column("favorite_count", sa.Integer(), nullable=False),
        sa.Column("last_reply_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reply_id", sa.Integer(), nullable=True),
        sa.Column(
            "hidden_by",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_forum_topics_hidden_by_users"),
            nullable=True,
        ),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_forum_topics_category_id", "forum_topics", ["category_id"], unique=False
    )
    op.create_index(
        "ix_forum_topics_author_id", "forum_topics", ["author_id"], unique=False
    )
    op.create_index("ix_forum_topics_status", "forum_topics", ["status"], unique=False)
    op.create_index(
        "ix_forum_topics_is_pinned", "forum_topics", ["is_pinned"], unique=False
    )
    op.create_index(
        "ix_forum_topics_last_reply_at", "forum_topics", ["last_reply_at"], unique=False
    )

    op.create_table(
        "forum_replies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "topic_id",
            sa.Integer(),
            sa.ForeignKey(
                "forum_topics.id", name="fk_forum_replies_topic_id_forum_topics"
            ),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_forum_replies_author_id_users"),
            nullable=False,
        ),
        sa.Column(
            "parent_reply_id",
            sa.Integer(),
            sa.ForeignKey(
                "forum_replies.id",
                name="fk_forum_replies_parent_reply_id_forum_replies",
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
            sa.ForeignKey("users.id", name="fk_forum_replies_hidden_by_users"),
            nullable=True,
        ),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_forum_replies_topic_id", "forum_replies", ["topic_id"], unique=False
    )
    op.create_index(
        "ix_forum_replies_author_id", "forum_replies", ["author_id"], unique=False
    )
    op.create_index(
        "ix_forum_replies_parent_reply_id",
        "forum_replies",
        ["parent_reply_id"],
        unique=False,
    )
    op.create_index(
        "ix_forum_replies_status", "forum_replies", ["status"], unique=False
    )

    op.create_foreign_key(
        "fk_forum_topics_last_reply_id_forum_replies",
        "forum_topics",
        "forum_replies",
        ["last_reply_id"],
        ["id"],
    )

    op.create_table(
        "forum_likes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_forum_likes_user_id_users"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "target_type", "target_id", name="ux_forum_likes_unique"
        ),
    )
    op.create_index("ix_forum_likes_user_id", "forum_likes", ["user_id"], unique=False)
    op.create_index(
        "idx_forum_likes_target",
        "forum_likes",
        ["target_type", "target_id"],
        unique=False,
    )

    op.create_table(
        "forum_favorites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_forum_favorites_user_id_users"),
            nullable=False,
        ),
        sa.Column(
            "topic_id",
            sa.Integer(),
            sa.ForeignKey(
                "forum_topics.id", name="fk_forum_favorites_topic_id_forum_topics"
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "topic_id", name="ux_forum_favorites_unique"),
    )
    op.create_index(
        "ix_forum_favorites_user_id", "forum_favorites", ["user_id"], unique=False
    )
    op.create_index(
        "ix_forum_favorites_topic_id", "forum_favorites", ["topic_id"], unique=False
    )

    op.create_table(
        "forum_topic_views",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "topic_id",
            sa.Integer(),
            sa.ForeignKey(
                "forum_topics.id", name="fk_forum_topic_views_topic_id_forum_topics"
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_forum_topic_views_user_id_users"),
            nullable=True,
        ),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_forum_topic_views_topic_id", "forum_topic_views", ["topic_id"], unique=False
    )
    # partial unique index：登录用户按 (topic_id, user_id) 去重，匿名按 (topic_id, ip_hash) 去重
    op.create_index(
        "idx_forum_topic_views_unique_user",
        "forum_topic_views",
        ["topic_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "idx_forum_topic_views_unique_ip",
        "forum_topic_views",
        ["topic_id", "ip_hash"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )

    op.create_table(
        "forum_mentions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "mentioned_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_forum_mentions_mentioned_user_id_users"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column(
            "source_author_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_forum_mentions_source_author_id_users"),
            nullable=True,
        ),
        sa.Column("is_notified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_forum_mentions_mentioned_user_id",
        "forum_mentions",
        ["mentioned_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_forum_mentions_is_notified", "forum_mentions", ["is_notified"], unique=False
    )

    # ---- 博客 ----
    op.create_table(
        "blog_series",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_blog_series_created_by_users"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug", name="uq_blog_series_slug"),
    )

    op.create_table(
        "blog_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("cover_image", sa.String(length=1024), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("tags", _JSONB, nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_blog_posts_author_id_users"),
            nullable=False,
        ),
        sa.Column(
            "series_id",
            sa.Integer(),
            sa.ForeignKey("blog_series.id", name="fk_blog_posts_series_id_blog_series"),
            nullable=True,
        ),
        sa.Column("series_order", sa.Integer(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False),
        sa.Column("like_count", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug", name="uq_blog_posts_slug"),
    )
    op.create_index("ix_blog_posts_category", "blog_posts", ["category"], unique=False)
    op.create_index("ix_blog_posts_status", "blog_posts", ["status"], unique=False)
    op.create_index(
        "ix_blog_posts_author_id", "blog_posts", ["author_id"], unique=False
    )
    op.create_index(
        "ix_blog_posts_published_at", "blog_posts", ["published_at"], unique=False
    )

    op.create_table(
        "blog_likes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "post_id",
            sa.Integer(),
            sa.ForeignKey("blog_posts.id", name="fk_blog_likes_post_id_blog_posts"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_blog_likes_user_id_users"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("post_id", "user_id", name="ux_blog_likes_unique"),
    )
    op.create_index("ix_blog_likes_post_id", "blog_likes", ["post_id"], unique=False)
    op.create_index("ix_blog_likes_user_id", "blog_likes", ["user_id"], unique=False)

    # ---- 通知 ----
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_notifications_user_id_users"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column(
            "sender_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_notifications_sender_id_users"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_notifications_user_id", "notifications", ["user_id"], unique=False
    )
    op.create_index(
        "ix_notifications_is_read", "notifications", ["is_read"], unique=False
    )

    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_dismissible", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_roles", _JSONB, nullable=True),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_announcements_created_by_users"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_announcements_is_active", "announcements", ["is_active"], unique=False
    )
    op.create_index(
        "ix_announcements_priority", "announcements", ["priority"], unique=False
    )

    # ---- 考试 ----
    op.create_table(
        "exams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("tech_tags", _JSONB, nullable=True),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_exams_created_by_users"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_exams_status", "exams", ["status"], unique=False)
    op.create_index("ix_exams_start_time", "exams", ["start_time"], unique=False)

    op.create_table(
        "exam_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "exam_id",
            sa.Integer(),
            sa.ForeignKey("exams.id", name="fk_exam_questions_exam_id_exams"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_exam_questions_exam_id", "exam_questions", ["exam_id"], unique=False
    )
    op.create_index(
        "ix_exam_questions_sort_order", "exam_questions", ["sort_order"], unique=False
    )

    op.create_table(
        "exam_question_options",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "question_id",
            sa.Integer(),
            sa.ForeignKey(
                "exam_questions.id",
                name="fk_exam_question_options_question_id_exam_questions",
            ),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_exam_question_options_question_id",
        "exam_question_options",
        ["question_id"],
        unique=False,
    )

    op.create_table(
        "exam_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_exam_attempts_user_id_users"),
            nullable=False,
        ),
        sa.Column(
            "exam_id",
            sa.Integer(),
            sa.ForeignKey("exams.id", name="fk_exam_attempts_exam_id_exams"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            sa.Integer(),
            sa.ForeignKey(
                "exam_questions.id", name="fk_exam_attempts_question_id_exam_questions"
            ),
            nullable=False,
        ),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "question_id", name="ux_exam_attempts_unique"),
    )
    op.create_index(
        "ix_exam_attempts_user_id", "exam_attempts", ["user_id"], unique=False
    )
    op.create_index(
        "ix_exam_attempts_exam_id", "exam_attempts", ["exam_id"], unique=False
    )
    op.create_index(
        "ix_exam_attempts_question_id", "exam_attempts", ["question_id"], unique=False
    )

    # ---- 任务 / 积分 ----
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("tags", _JSONB, nullable=True),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("max_claimants", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_tasks_created_by_users"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"], unique=False)
    op.create_index("ix_tasks_category", "tasks", ["category"], unique=False)
    op.create_index("ix_tasks_created_by", "tasks", ["created_by"], unique=False)

    op.create_table(
        "task_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", name="fk_task_claims_task_id_tasks"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_task_claims_user_id_users"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("claim_note", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reviewed_by",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_task_claims_reviewed_by_users"),
            nullable=True,
        ),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "user_id", name="ux_task_claims_unique"),
    )
    op.create_index("ix_task_claims_task_id", "task_claims", ["task_id"], unique=False)
    op.create_index("ix_task_claims_user_id", "task_claims", ["user_id"], unique=False)
    op.create_index("ix_task_claims_status", "task_claims", ["status"], unique=False)

    op.create_table(
        "points_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_points_transactions_user_id_users"),
            nullable=False,
        ),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_points_transactions_user_id",
        "points_transactions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_points_transactions_created_at",
        "points_transactions",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_points_transactions_created_at", table_name="points_transactions")
    op.drop_index("ix_points_transactions_user_id", table_name="points_transactions")
    op.drop_table("points_transactions")

    op.drop_index("ix_task_claims_status", table_name="task_claims")
    op.drop_index("ix_task_claims_user_id", table_name="task_claims")
    op.drop_index("ix_task_claims_task_id", table_name="task_claims")
    op.drop_table("task_claims")

    op.drop_index("ix_tasks_created_by", table_name="tasks")
    op.drop_index("ix_tasks_category", table_name="tasks")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_table("tasks")

    op.drop_index("ix_exam_attempts_question_id", table_name="exam_attempts")
    op.drop_index("ix_exam_attempts_exam_id", table_name="exam_attempts")
    op.drop_index("ix_exam_attempts_user_id", table_name="exam_attempts")
    op.drop_table("exam_attempts")

    op.drop_index(
        "ix_exam_question_options_question_id", table_name="exam_question_options"
    )
    op.drop_table("exam_question_options")

    op.drop_index("ix_exam_questions_sort_order", table_name="exam_questions")
    op.drop_index("ix_exam_questions_exam_id", table_name="exam_questions")
    op.drop_table("exam_questions")

    op.drop_index("ix_exams_start_time", table_name="exams")
    op.drop_index("ix_exams_status", table_name="exams")
    op.drop_table("exams")

    op.drop_index("ix_announcements_priority", table_name="announcements")
    op.drop_index("ix_announcements_is_active", table_name="announcements")
    op.drop_table("announcements")

    op.drop_index("ix_notifications_is_read", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index("ix_blog_likes_user_id", table_name="blog_likes")
    op.drop_index("ix_blog_likes_post_id", table_name="blog_likes")
    op.drop_table("blog_likes")

    op.drop_index("ix_blog_posts_published_at", table_name="blog_posts")
    op.drop_index("ix_blog_posts_author_id", table_name="blog_posts")
    op.drop_index("ix_blog_posts_status", table_name="blog_posts")
    op.drop_index("ix_blog_posts_category", table_name="blog_posts")
    op.drop_table("blog_posts")

    op.drop_table("blog_series")

    op.drop_index("ix_forum_mentions_is_notified", table_name="forum_mentions")
    op.drop_index("ix_forum_mentions_mentioned_user_id", table_name="forum_mentions")
    op.drop_table("forum_mentions")

    op.drop_index("idx_forum_topic_views_unique_ip", table_name="forum_topic_views")
    op.drop_index("idx_forum_topic_views_unique_user", table_name="forum_topic_views")
    op.drop_index("ix_forum_topic_views_topic_id", table_name="forum_topic_views")
    op.drop_table("forum_topic_views")

    op.drop_index("ix_forum_favorites_topic_id", table_name="forum_favorites")
    op.drop_index("ix_forum_favorites_user_id", table_name="forum_favorites")
    op.drop_table("forum_favorites")

    op.drop_index("idx_forum_likes_target", table_name="forum_likes")
    op.drop_index("ix_forum_likes_user_id", table_name="forum_likes")
    op.drop_table("forum_likes")

    op.drop_constraint(
        "fk_forum_topics_last_reply_id_forum_replies",
        "forum_topics",
        type_="foreignkey",
    )

    op.drop_index("ix_forum_replies_status", table_name="forum_replies")
    op.drop_index("ix_forum_replies_parent_reply_id", table_name="forum_replies")
    op.drop_index("ix_forum_replies_author_id", table_name="forum_replies")
    op.drop_index("ix_forum_replies_topic_id", table_name="forum_replies")
    op.drop_table("forum_replies")

    op.drop_index("ix_forum_topics_last_reply_at", table_name="forum_topics")
    op.drop_index("ix_forum_topics_is_pinned", table_name="forum_topics")
    op.drop_index("ix_forum_topics_status", table_name="forum_topics")
    op.drop_index("ix_forum_topics_author_id", table_name="forum_topics")
    op.drop_index("ix_forum_topics_category_id", table_name="forum_topics")
    op.drop_table("forum_topics")

    op.drop_index("ix_forum_categories_sort_order", table_name="forum_categories")
    op.drop_table("forum_categories")

    op.drop_index(
        "ix_activity_participations_user_id", table_name="activity_participations"
    )
    op.drop_table("activity_participations")

    op.drop_index("ix_event_checkins_checkin_code", table_name="event_checkins")
    op.drop_index("ix_event_checkins_event_id", table_name="event_checkins")
    op.drop_table("event_checkins")

    op.drop_index("ix_event_registrations_event_id", table_name="event_registrations")
    op.drop_index("ix_event_registrations_user_id", table_name="event_registrations")
    op.drop_table("event_registrations")

    op.drop_index("ix_events_date", table_name="events")
    op.drop_index("ix_events_status", table_name="events")
    op.drop_index("ix_events_is_pinned", table_name="events")
    op.drop_table("events")

    op.drop_index("ix_join_applications_user_id", table_name="join_applications")
    op.drop_index("ix_join_applications_created_at", table_name="join_applications")
    op.drop_index("ix_join_applications_status", table_name="join_applications")
    op.drop_table("join_applications")

    op.drop_index(
        "ix_component_registry_guides_item_id", table_name="component_registry_guides"
    )
    op.drop_table("component_registry_guides")

    op.drop_index(
        "ix_component_registry_variants_item_id",
        table_name="component_registry_variants",
    )
    op.drop_table("component_registry_variants")

    op.drop_index(
        "ix_component_registry_items_migration_status",
        table_name="component_registry_items",
    )
    op.drop_index(
        "ix_component_registry_items_category", table_name="component_registry_items"
    )
    op.drop_table("component_registry_items")

    op.drop_index("ix_resources_created_at", table_name="resources")
    op.drop_index("ix_resources_submitted_by", table_name="resources")
    op.drop_index("ix_resources_status", table_name="resources")
    op.drop_index("ix_resources_resource_type", table_name="resources")
    op.drop_table("resources")

    op.drop_index("ix_settings_module", table_name="settings")
    op.drop_table("settings")

    op.drop_index(
        "ix_password_reset_requests_status", table_name="password_reset_requests"
    )
    op.drop_table("password_reset_requests")

    op.drop_table("two_factor_auth")

    op.drop_index("ix_verification_codes_expires_at", table_name="verification_codes")
    op.drop_index("ix_verification_codes_email", table_name="verification_codes")
    op.drop_table("verification_codes")

    op.drop_index("idx_password_history_user", table_name="password_history")
    op.drop_index("ix_password_history_user_id", table_name="password_history")
    op.drop_table("password_history")

    op.drop_index("idx_login_history_attempted_email", table_name="login_history")
    op.drop_index("idx_login_history_user", table_name="login_history")
    op.drop_index("ix_login_history_user_id", table_name="login_history")
    op.drop_table("login_history")

    _drop_users_business_columns()
