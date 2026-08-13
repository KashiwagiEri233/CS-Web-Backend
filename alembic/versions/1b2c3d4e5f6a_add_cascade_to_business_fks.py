"""add on delete cascade to business parent FKs

考试/任务/活动等业务主体删除时级联清理子表（与测试清理与产品语义一致）：
- exam_questions.exam_id / exam_question_options.question_id /
  exam_attempts.exam_id+question_id
- task_claims.task_id
- event_registrations.event_id / event_checkins.event_id+registration_id /
  activity_participations.event_id

Revision ID: 1b2c3d4e5f6a
Revises: 3a4b5c6d7e8f
Create Date: 2026-08-03

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1b2c3d4e5f6a"
down_revision: Union[str, Sequence[str], None] = "3a4b5c6d7e8f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FKS: list[tuple[str, str, str, str, str]] = [
    # (constraint, table, ref_table, column, ref_column)
    ("fk_exam_questions_exam_id_exams", "exam_questions", "exams", "exam_id", "id"),
    (
        "fk_exam_question_options_question_id_exam_questions",
        "exam_question_options",
        "exam_questions",
        "question_id",
        "id",
    ),
    ("fk_exam_attempts_exam_id_exams", "exam_attempts", "exams", "exam_id", "id"),
    (
        "fk_exam_attempts_question_id_exam_questions",
        "exam_attempts",
        "exam_questions",
        "question_id",
        "id",
    ),
    ("fk_task_claims_task_id_tasks", "task_claims", "tasks", "task_id", "id"),
    (
        "fk_event_registrations_event_id_events",
        "event_registrations",
        "events",
        "event_id",
        "id",
    ),
    ("fk_event_checkins_event_id_events", "event_checkins", "events", "event_id", "id"),
    (
        "fk_event_checkins_registration_id_event_registrations",
        "event_checkins",
        "event_registrations",
        "registration_id",
        "id",
    ),
]


def upgrade() -> None:
    """Upgrade schema."""
    for name, table, ref_table, column, ref_column in _FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name, table, ref_table, [column], [ref_column], ondelete="CASCADE"
        )


def downgrade() -> None:
    """Downgrade schema."""
    for name, table, ref_table, column, ref_column in reversed(_FKS):
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, ref_table, [column], [ref_column])
