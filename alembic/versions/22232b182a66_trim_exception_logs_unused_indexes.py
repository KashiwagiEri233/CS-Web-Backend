"""trim exception_logs unused indexes

写密集的异常日志表原本为几乎无查询场景的列（endpoint/request_id/severity/
priority/related_incident_id）维护单列索引，外加两个冗余复合索引
（idx_traceback_id_user、idx_created_at_severity），拖慢每次异常插入。
列表查询只按 type/code/status/user/resolved/created 过滤，相应索引保留。

Revision ID: 22232b182a66
Revises: c41e8d7a2f90
Create Date: 2026-07-21 12:56:49.609379

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "22232b182a66"
down_revision: Union[str, Sequence[str], None] = "c41e8d7a2f90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index("idx_created_at_severity", table_name="exception_logs")
    op.drop_index("idx_traceback_id_user", table_name="exception_logs")
    op.drop_index("ix_exception_logs_endpoint", table_name="exception_logs")
    op.drop_index("ix_exception_logs_priority", table_name="exception_logs")
    op.drop_index("ix_exception_logs_related_incident_id", table_name="exception_logs")
    op.drop_index("ix_exception_logs_request_id", table_name="exception_logs")
    op.drop_index("ix_exception_logs_severity", table_name="exception_logs")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_index(
        "ix_exception_logs_severity", "exception_logs", ["severity"], unique=False
    )
    op.create_index(
        "ix_exception_logs_request_id", "exception_logs", ["request_id"], unique=False
    )
    op.create_index(
        "ix_exception_logs_related_incident_id",
        "exception_logs",
        ["related_incident_id"],
        unique=False,
    )
    op.create_index(
        "ix_exception_logs_priority", "exception_logs", ["priority"], unique=False
    )
    op.create_index(
        "ix_exception_logs_endpoint", "exception_logs", ["endpoint"], unique=False
    )
    op.create_index(
        "idx_traceback_id_user",
        "exception_logs",
        ["traceback_id", "user_id"],
        unique=False,
    )
    op.create_index(
        "idx_created_at_severity",
        "exception_logs",
        ["created_at", "severity"],
        unique=False,
    )
