"""add user wrong-answer snapshots and review state"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learning_wrong_answers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("question_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("knowledge_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("latest_answer", sa.Text(), nullable=True),
        sa.Column("correct_answer", sa.Text(), nullable=True),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column("mistake_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_wrong_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["exam_questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "question_id", name="ux_learning_wrong_answers_user_question"),
    )
    for name, column in (
        ("user_id", "user_id"),
        ("exam_id", "exam_id"),
        ("question_id", "question_id"),
        ("status", "status"),
        ("review_due_at", "review_due_at"),
    ):
        op.create_index(op.f(f"ix_learning_wrong_answers_{name}"), "learning_wrong_answers", [column], unique=False)


def downgrade() -> None:
    for name in ("review_due_at", "status", "question_id", "exam_id", "user_id"):
        op.drop_index(op.f(f"ix_learning_wrong_answers_{name}"), table_name="learning_wrong_answers")
    op.drop_table("learning_wrong_answers")
