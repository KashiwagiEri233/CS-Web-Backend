"""prune redundant indexes and add association reverse indexes

Revision ID: d52f1a6c8b73
Revises: c41e8d7a2f90
Create Date: 2026-07-26 00:00:00.000000

三类调整（与模型定义同步）：

1. 删除主键上的冗余索引。PostgreSQL 为主键自动创建唯一索引，模型里额外的
   ``index=True`` 会再建一个 ``ix_<table>_id``，对查询毫无帮助，只增加每次
   INSERT/UPDATE 的索引维护成本。

2. 精简 ``exception_logs`` 的索引（承接 22232b182a66 已删除的那批，本迁移只处理
   剩下被复合索引前缀覆盖的单列索引）。该表写多读少：
   - exception_type / error_code / status_code / user_id 的单列索引被对应的
     ``idx_*_created`` 复合索引最左前缀完全覆盖；
   - idx_traceback_id_user、idx_created_at_severity 的最左列各自已有单列索引，
     而第二列（user_id / severity）从不与之组合查询；
   - endpoint / severity / priority / related_incident_id 没有任何查询使用
     （severity、priority 还是 2-3 个取值的低基数列，选择性极差）。

3. 为多对多关联表补反向索引。``user_roles`` 的复合主键是 (user_id, role_id)，
   只能加速按 user_id 的查询；按 role_id 反查（``get_user_ids_by_role``、鉴权
   join）会退化为顺序扫描。``role_permissions`` 的 permission_id 同理。

运维提示：DROP INDEX 与 CREATE INDEX 会短暂持有表级锁。这里涉及的关联表数据量
很小（角色数 × 用户数），而 DROP INDEX 本身是元数据操作，正常规模下耗时可忽略。
若 exception_logs 已积累到千万级且不能接受任何写阻塞，可改为在维护窗口外单独执行
``DROP INDEX CONCURRENTLY``（不能在事务内运行，故不放进本迁移）。
"""

from typing import List, Sequence, Tuple, Union

from alembic import op

revision: str = "d52f1a6c8b73"
down_revision: Union[str, Sequence[str], None] = "22232b182a66"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (索引名, 表名, 列) —— upgrade 删除、downgrade 原样重建。
# 用同一份数据驱动两个方向，避免 downgrade 漏掉某个索引（CI 会跑
# upgrade -> downgrade base -> upgrade 往返）。
_DROPPED_INDEXES: List[Tuple[str, str, List[str]]] = [
    # 1. 主键冗余索引
    ("ix_users_id", "users", ["id"]),
    ("ix_roles_id", "roles", ["id"]),
    ("ix_permissions_id", "permissions", ["id"]),
    ("ix_refresh_tokens_id", "refresh_tokens", ["id"]),
    ("ix_audit_logs_id", "audit_logs", ["id"]),
    ("ix_exception_logs_id", "exception_logs", ["id"]),
    # 2a. exception_logs：被 idx_*_created 复合索引前缀覆盖的单列索引
    ("ix_exception_logs_exception_type", "exception_logs", ["exception_type"]),
    ("ix_exception_logs_error_code", "exception_logs", ["error_code"]),
    ("ix_exception_logs_status_code", "exception_logs", ["status_code"]),
    ("ix_exception_logs_user_id", "exception_logs", ["user_id"]),
]

# 3. 关联表反向索引：upgrade 创建、downgrade 删除。
_ADDED_INDEXES: List[Tuple[str, str, List[str]]] = [
    ("ix_user_roles_role_id", "user_roles", ["role_id"]),
    ("ix_role_permissions_permission_id", "role_permissions", ["permission_id"]),
]


def upgrade() -> None:
    for name, table, _columns in _DROPPED_INDEXES:
        op.drop_index(op.f(name), table_name=table)

    for name, table, columns in _ADDED_INDEXES:
        op.create_index(op.f(name), table, columns, unique=False)


def downgrade() -> None:
    for name, table, _columns in reversed(_ADDED_INDEXES):
        op.drop_index(op.f(name), table_name=table)

    for name, table, columns in reversed(_DROPPED_INDEXES):
        op.create_index(op.f(name), table, columns, unique=False)
