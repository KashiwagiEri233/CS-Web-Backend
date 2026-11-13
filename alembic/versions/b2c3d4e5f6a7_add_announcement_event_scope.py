"""add announcement visibility/status and event real time/scope

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-04

P4：公告增加可见范围与发布状态；活动增加真实起止时间、地点、主办与组织范围。
旧状态仅做契约映射（planned→upcoming、completed→ended），不导入旧活动数据。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------ announcements
    op.add_column(
        "announcements",
        sa.Column(
            "visibility",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'public'"),
        ),
    )
    op.add_column("announcements", sa.Column("peak_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "announcements",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
    )
    op.add_column(
        "announcements",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "announcements",
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
    )
    op.execute(
        "UPDATE announcements SET status = 'published', published_at = created_at "
        "WHERE is_active = true"
    )
    op.execute(
        "UPDATE announcements SET status = 'archived' WHERE is_active = false"
    )
    op.create_foreign_key(
        "fk_announcements_peak_id_peaks",
        "announcements",
        "peaks",
        ["peak_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_announcements_status",
        "announcements",
        "status IN ('draft', 'published', 'archived')",
    )
    op.create_check_constraint(
        "ck_announcements_visibility",
        "announcements",
        "visibility IN ('public', 'members', 'peak')",
    )
    op.create_check_constraint(
        "ck_announcements_peak_visibility",
        "announcements",
        "visibility <> 'peak' OR peak_id IS NOT NULL",
    )
    op.create_index(
        "ix_announcements_status_published",
        "announcements",
        ["status", "published_at", "id"],
    )
    op.create_index("ix_announcements_expires", "announcements", ["expires_at"])
    op.create_index("ix_announcements_created_by", "announcements", ["created_by"])

    # ----------------------------------------------------------------- events
    op.add_column(
        "events", sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "events", sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("events", sa.Column("location", sa.String(length=255), nullable=True))
    op.add_column("events", sa.Column("organizer_id", sa.Integer(), nullable=True))
    op.add_column(
        "events",
        sa.Column(
            "visibility",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'public'"),
        ),
    )
    op.add_column("events", sa.Column("peak_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "events",
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
    )
    op.execute("UPDATE events SET status = 'upcoming' WHERE status = 'planned'")
    op.execute("UPDATE events SET status = 'ended' WHERE status = 'completed'")
    op.create_foreign_key(
        "fk_events_organizer_id_users",
        "events",
        "users",
        ["organizer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_events_peak_id_peaks",
        "events",
        "peaks",
        ["peak_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint("ck_events_capacity", "events", "capacity >= 0")
    op.create_check_constraint(
        "ck_events_time_order",
        "events",
        "starts_at IS NULL OR ends_at IS NULL OR starts_at < ends_at",
    )
    op.create_check_constraint(
        "ck_events_visibility", "events", "visibility IN ('public', 'members', 'peak')"
    )
    op.create_check_constraint(
        "ck_events_peak_visibility", "events", "visibility <> 'peak' OR peak_id IS NOT NULL"
    )
    op.create_index(
        "ix_events_visibility_peak_status",
        "events",
        ["visibility", "peak_id", "status", "starts_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_events_visibility_peak_status", table_name="events")
    op.drop_constraint("ck_events_peak_visibility", "events", type_="check")
    op.drop_constraint("ck_events_visibility", "events", type_="check")
    op.drop_constraint("ck_events_time_order", "events", type_="check")
    op.drop_constraint("ck_events_capacity", "events", type_="check")
    op.drop_constraint("fk_events_peak_id_peaks", "events", type_="foreignkey")
    op.drop_constraint("fk_events_organizer_id_users", "events", type_="foreignkey")
    op.drop_column("events", "version")
    op.drop_column("events", "peak_id")
    op.drop_column("events", "visibility")
    op.drop_column("events", "organizer_id")
    op.drop_column("events", "location")
    op.drop_column("events", "ends_at")
    op.drop_column("events", "starts_at")

    op.drop_index("ix_announcements_created_by", table_name="announcements")
    op.drop_index("ix_announcements_expires", table_name="announcements")
    op.drop_index("ix_announcements_status_published", table_name="announcements")
    op.drop_constraint(
        "ck_announcements_peak_visibility", "announcements", type_="check"
    )
    op.drop_constraint("ck_announcements_visibility", "announcements", type_="check")
    op.drop_constraint("ck_announcements_status", "announcements", type_="check")
    op.drop_constraint(
        "fk_announcements_peak_id_peaks", "announcements", type_="foreignkey"
    )
    op.drop_column("announcements", "version")
    op.drop_column("announcements", "published_at")
    op.drop_column("announcements", "status")
    op.drop_column("announcements", "peak_id")
    op.drop_column("announcements", "visibility")
