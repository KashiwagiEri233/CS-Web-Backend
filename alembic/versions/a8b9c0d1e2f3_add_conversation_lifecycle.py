"""add archive and soft-delete timestamps to conversations"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_conversations_archived_at"),
        "conversations",
        ["archived_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversations_deleted_at"),
        "conversations",
        ["deleted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_conversations_deleted_at"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_archived_at"), table_name="conversations")
    op.drop_column("conversations", "deleted_at")
    op.drop_column("conversations", "archived_at")
