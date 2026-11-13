"""add legacy sync (users.sync_id + outbox/state)"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users.sync_id：官网与旧项目用户稳定映射键（幂等 upsert 依据 + 行为主体取值）。
    # 允许为空：存量用户由对账任务回填。
    op.add_column("users", sa.Column("sync_id", sa.String(length=64), nullable=True))
    op.create_index("ix_users_sync_id", "users", ["sync_id"], unique=True)

    # 待同步 outbox：推送旧项目失败后的回落存储，定时任务重放。
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

    # 同步运行态：按 key 记录水位线（键值表）。
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


def downgrade() -> None:
    op.drop_index(op.f("ix_legacy_sync_state_key"), table_name="legacy_sync_state")
    op.drop_table("legacy_sync_state")

    op.drop_index(
        op.f("ix_legacy_sync_outbox_sync_id"), table_name="legacy_sync_outbox"
    )
    op.drop_table("legacy_sync_outbox")

    op.drop_index("ix_users_sync_id", table_name="users")
    op.drop_column("users", "sync_id")