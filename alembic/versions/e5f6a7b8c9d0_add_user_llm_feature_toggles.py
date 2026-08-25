"""add user-level feature toggles to llm_configs

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-20

用户级功能开关（前端设置面板）：web_search_enabled（联网搜索）、trajectory_enabled（Trajectory 事件记录）。
默认 True（与旧行为一致：未设置开关前功能可用）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "llm_configs",
        sa.Column(
            "web_search_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "llm_configs",
        sa.Column(
            "trajectory_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("llm_configs", "trajectory_enabled")
    op.drop_column("llm_configs", "web_search_enabled")
