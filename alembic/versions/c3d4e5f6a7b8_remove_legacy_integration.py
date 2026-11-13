"""remove legacy integration tables

移除旧项目外接链路遗留表（P7 contract migration）：
- legacy_sync_outbox / legacy_sync_state：旧项目用户同步 outbox 与水位线；
- points_transactions：旧积分账本（统一钱包后不再使用）。

说明：
- 代码调用者已在同一变更集中全部移除，`check_legacy_removal.py` 零命中；
- `users.sync_id` 保留为历史身份映射，不在本迁移删除；
- downgrade 仅重建空表结构，不恢复历史数据（破坏性 contract 迁移）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_legacy_sync_outbox_sync_id", table_name="legacy_sync_outbox")
    op.drop_table("legacy_sync_outbox")
    op.drop_index("ix_legacy_sync_state_key", table_name="legacy_sync_state")
    op.drop_table("legacy_sync_state")
    op.drop_index("ix_points_transactions_created_at", table_name="points_transactions")
    op.drop_index("ix_points_transactions_user_id", table_name="points_transactions")
    op.drop_table("points_transactions")


def downgrade() -> None:
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

    op.create_table(
        "legacy_sync_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_legacy_sync_state_key"), "legacy_sync_state", ["key"], unique=True
    )

    op.create_table(
        "legacy_sync_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity", sa.String(length=30), nullable=False),
        sa.Column("sync_id", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity", "sync_id", name="ux_legacy_sync_outbox_entity_sync"
        ),
    )
    op.create_index(
        op.f("ix_legacy_sync_outbox_sync_id"),
        "legacy_sync_outbox",
        ["sync_id"],
        unique=False,
    )
