"""add task_claims.submission_url

Revision ID: b8c9d0e1f2a3
Revises: f3a4b5c6d7e8
Create Date: 2026-09-14

任务完成提交的证明材料链接落库（TOOLS-GOV Slice E）：此前 BFF 提交
submission_url 但 TaskClaim 无对应存储列，数据被静默丢弃。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "task_claims",
        sa.Column("submission_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task_claims", "submission_url")
