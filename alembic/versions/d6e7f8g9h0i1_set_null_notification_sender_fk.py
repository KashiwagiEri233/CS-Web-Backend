"""set on delete set null for notification sender FK

通知的 sender_id（发送者）在用户被删除后应置空而非阻断删除
（收件人通知保留，发送者信息消失）。

Revision ID: d6e7f8g9h0i1
Revises: f0a1b2c3d4e5
Create Date: 2026-08-03

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d6e7f8g9h0i1"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NAME = "fk_notifications_sender_id_users"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(_NAME, "notifications", type_="foreignkey")
    op.create_foreign_key(
        _NAME, "notifications", "users", ["sender_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(_NAME, "notifications", type_="foreignkey")
    op.create_foreign_key(_NAME, "notifications", "users", ["sender_id"], ["id"])
