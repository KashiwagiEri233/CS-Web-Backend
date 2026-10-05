"""add agent automation rules (AG-P3-02 自动化规则)"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_automation_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("condition", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "action_type",
            sa.String(length=32),
            nullable=False,
            server_default="inbox_suggestion",
        ),
        sa.Column("action_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("quiet_hours_start", sa.String(length=5), nullable=True),
        sa.Column("quiet_hours_end", sa.String(length=5), nullable=True),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="240"),
        sa.Column("max_per_hour", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ("user_id", "trigger_type", "enabled"):
        op.create_index(
            op.f(f"ix_agent_automation_rules_{name}"),
            "agent_automation_rules",
            [name],
            unique=False,
        )


def downgrade() -> None:
    for name in ("enabled", "trigger_type", "user_id"):
        op.drop_index(
            op.f(f"ix_agent_automation_rules_{name}"),
            table_name="agent_automation_rules",
        )
    op.drop_table("agent_automation_rules")
