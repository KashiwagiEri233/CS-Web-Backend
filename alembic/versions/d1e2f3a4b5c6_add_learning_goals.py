"""add learning goals and weekly study budgets"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learning_goals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("exam_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("weekly_budget_minutes", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("preferred_slots", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, column in (
        ("user_id", "user_id"),
        ("exam_id", "exam_id"),
        ("target_date", "target_date"),
        ("status", "status"),
    ):
        op.create_index(
            op.f(f"ix_learning_goals_{name}"),
            "learning_goals",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for name in ("status", "target_date", "exam_id", "user_id"):
        op.drop_index(op.f(f"ix_learning_goals_{name}"), table_name="learning_goals")
    op.drop_table("learning_goals")
