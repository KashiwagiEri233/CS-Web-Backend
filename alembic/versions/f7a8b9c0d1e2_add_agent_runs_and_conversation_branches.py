"""add agent runs and conversation branch metadata

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-08-21

Agent runtime correctness and first-generation conversation branches. Existing
chat events remain readable with a nullable run_id; new events are unique per run.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("trigger_type", sa.String(length=20), nullable=False, server_default="chat"),
        sa.Column("preset_id", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("input_message_id", sa.Integer(), nullable=True),
        sa.Column("output_message_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["input_message_id"], ["chat_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["output_message_id"], ["chat_messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_runs_user_id"), "agent_runs", ["user_id"], unique=False)
    op.create_index(op.f("ix_agent_runs_conversation_id"), "agent_runs", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_agent_runs_status"), "agent_runs", ["status"], unique=False)

    op.add_column(
        "conversations",
        sa.Column("parent_conversation_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("root_conversation_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("forked_from_message_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_conversations_parent_conversation_id",
        "conversations", "conversations", ["parent_conversation_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_conversations_root_conversation_id",
        "conversations", "conversations", ["root_conversation_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_conversations_forked_from_message_id",
        "conversations", "chat_messages", ["forked_from_message_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(op.f("ix_conversations_parent_conversation_id"), "conversations", ["parent_conversation_id"], unique=False)
    op.create_index(op.f("ix_conversations_root_conversation_id"), "conversations", ["root_conversation_id"], unique=False)
    op.create_index(op.f("ix_conversations_forked_from_message_id"), "conversations", ["forked_from_message_id"], unique=False)

    op.add_column("chat_events", sa.Column("run_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_chat_events_run_id", "chat_events", "agent_runs", ["run_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index(op.f("ix_chat_events_run_id"), "chat_events", ["run_id"], unique=False)
    op.drop_constraint("uq_chat_events_conv_seq", "chat_events", type_="unique")
    op.create_unique_constraint("uq_chat_events_run_seq", "chat_events", ["run_id", "seq"])


def downgrade() -> None:
    op.drop_constraint("uq_chat_events_run_seq", "chat_events", type_="unique")
    # 多个 run 的 seq 都从 1 开始；回退旧约束前按会话时间线重新连续编号。
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY conversation_id ORDER BY created_at, id
                   ) AS new_seq
            FROM chat_events
        )
        UPDATE chat_events AS event
        SET seq = ranked.new_seq
        FROM ranked
        WHERE event.id = ranked.id
        """
    )
    op.create_unique_constraint("uq_chat_events_conv_seq", "chat_events", ["conversation_id", "seq"])
    op.drop_index(op.f("ix_chat_events_run_id"), table_name="chat_events")
    op.drop_constraint("fk_chat_events_run_id", "chat_events", type_="foreignkey")
    op.drop_column("chat_events", "run_id")
    op.drop_index(op.f("ix_conversations_forked_from_message_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_root_conversation_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_parent_conversation_id"), table_name="conversations")
    op.drop_constraint("fk_conversations_forked_from_message_id", "conversations", type_="foreignkey")
    op.drop_constraint("fk_conversations_root_conversation_id", "conversations", type_="foreignkey")
    op.drop_constraint("fk_conversations_parent_conversation_id", "conversations", type_="foreignkey")
    op.drop_column("conversations", "forked_from_message_id")
    op.drop_column("conversations", "root_conversation_id")
    op.drop_column("conversations", "parent_conversation_id")
    op.drop_index(op.f("ix_agent_runs_status"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_conversation_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_user_id"), table_name="agent_runs")
    op.drop_table("agent_runs")
