"""add chat_events trajectory log

Revision ID: d4e5f6a7b8c9
Revises: d3e4f5a6b7c8
Create Date: 2026-08-19

融合点 2（Trajectory 事件日志）：学习助手对话全事件流 append-only 落库，
记录模型看到/产出的一切（delta / tool_call / tool_result / usage / done / error）。
现有 chat_messages 保留为对外快照。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chat_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "seq", name="uq_chat_events_conv_seq"),
    )
    op.create_index(
        op.f("ix_chat_events_conversation_id"),
        "chat_events",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_events_user_id"),
        "chat_events",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_chat_events_user_id"), table_name="chat_events")
    op.drop_index(op.f("ix_chat_events_conversation_id"), table_name="chat_events")
    op.drop_table("chat_events")
