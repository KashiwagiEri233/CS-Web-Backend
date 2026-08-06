"""convert json columns to jsonb and align audit_logs indexes with query shape

Revision ID: e6a4b91d70c2
Revises: d52f1a6c8b73
Create Date: 2026-07-26 00:00:00.000000

两部分：

1. ``json`` -> ``jsonb``（audit_logs.detail、exception_logs.details / context）。
   PostgreSQL 的 ``json`` 按原始文本存储，每次读取重新解析且无法建 GIN 索引；
   ``jsonb`` 是解析后的二进制格式。这几列都是「写一次、之后按内容检索」的用法。
   转换用 ``USING col::jsonb``，已有数据原样保留（合法 JSON 文本必然可转）。

2. audit_logs 索引重排。``AuditLogRepository.list_logs`` 恒定
   ``ORDER BY created_at DESC`` 并按单列过滤，原来的 4 个孤立单列索引只能加速过滤、
   排序仍要回表重排；换成 ``(过滤列, created_at)`` 复合索引后过滤与排序一次吃掉。
   created_at 单列索引保留（无过滤条件的列表查询与保留期清理要用）。

运维提示：``ALTER TABLE ... TYPE jsonb`` 会重写整张表并持有 ACCESS EXCLUSIVE 锁。
表很大时应安排在维护窗口执行，或改用「新增 jsonb 列 -> 双写回填 -> 切换」的在线方案。
"""

from typing import List, Sequence, Tuple, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6a4b91d70c2"
down_revision: Union[str, Sequence[str], None] = "d52f1a6c8b73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (表名, 列名, 是否可空)
_JSON_COLUMNS: List[Tuple[str, str, bool]] = [
    ("audit_logs", "detail", True),
    ("exception_logs", "details", True),
    ("exception_logs", "context", True),
]

# audit_logs：旧的孤立单列索引 -> 新的 (过滤列, created_at) 复合索引
_OLD_AUDIT_INDEXES: List[Tuple[str, List[str]]] = [
    ("ix_audit_logs_action", ["action"]),
    ("ix_audit_logs_resource_type", ["resource_type"]),
    ("ix_audit_logs_resource_id", ["resource_id"]),
    ("ix_audit_logs_actor_id", ["actor_id"]),
]

_NEW_AUDIT_INDEXES: List[Tuple[str, List[str]]] = [
    ("idx_audit_action_created", ["action", "created_at"]),
    ("idx_audit_resource_type_created", ["resource_type", "created_at"]),
    ("idx_audit_resource_id_created", ["resource_id", "created_at"]),
    ("idx_audit_actor_created", ["actor_id", "created_at"]),
]


def upgrade() -> None:
    for table, column, nullable in _JSON_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.JSON(),
            type_=postgresql.JSONB(astext_type=sa.Text()),
            existing_nullable=nullable,
            postgresql_using=f"{column}::jsonb",
        )

    for name, _columns in _OLD_AUDIT_INDEXES:
        op.drop_index(op.f(name), table_name="audit_logs")

    for name, columns in _NEW_AUDIT_INDEXES:
        op.create_index(op.f(name), "audit_logs", columns, unique=False)


def downgrade() -> None:
    for name, _columns in reversed(_NEW_AUDIT_INDEXES):
        op.drop_index(op.f(name), table_name="audit_logs")

    for name, columns in reversed(_OLD_AUDIT_INDEXES):
        op.create_index(op.f(name), "audit_logs", columns, unique=False)

    for table, column, nullable in reversed(_JSON_COLUMNS):
        op.alter_column(
            table,
            column,
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            type_=sa.JSON(),
            existing_nullable=nullable,
            postgresql_using=f"{column}::json",
        )
