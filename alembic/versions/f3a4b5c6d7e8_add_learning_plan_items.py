"""add adaptive learning plan items"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learning_plan_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=True),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "estimated_minutes", sa.Integer(), nullable=False, server_default="25"
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="planned"
        ),
        sa.Column(
            "locked", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["goal_id"], ["learning_goals.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "plan_date",
            "source_type",
            "source_key",
            name="ux_learning_plan_items_user_date_source",
        ),
    )
    for name, columns in (
        ("user_id", ["user_id"]),
        ("goal_id", ["goal_id"]),
        ("plan_date", ["plan_date"]),
        ("status", ["status"]),
    ):
        op.create_index(
            op.f(f"ix_learning_plan_items_{name}"),
            "learning_plan_items",
            columns,
            unique=False,
        )


def downgrade() -> None:
    for name in ("status", "plan_date", "goal_id", "user_id"):
        op.drop_index(
            op.f(f"ix_learning_plan_items_{name}"), table_name="learning_plan_items"
        )
    op.drop_table("learning_plan_items")
