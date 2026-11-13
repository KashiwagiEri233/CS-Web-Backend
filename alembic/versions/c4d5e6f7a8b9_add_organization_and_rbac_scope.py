"""add organization profiles and RBAC scope bindings

Revision ID: c4d5e6f7a8b9
Revises: b7c8d9e0f1a2
Create Date: 2026-11-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ 组织
    op.create_table(
        "peaks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("fantasy_name", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_peaks_code"),
    )
    op.create_index(
        "ix_peaks_active_archived", "peaks", ["is_active", "archived_at"], unique=False
    )

    op.create_table(
        "member_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.String(length=50), nullable=True),
        sa.Column("peak_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "membership_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["peak_id"], ["peaks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_member_profiles_user_id"),
    )
    op.create_index(
        "uq_member_profiles_student_id",
        "member_profiles",
        ["student_id"],
        unique=True,
        postgresql_where=sa.text("student_id IS NOT NULL"),
    )
    op.create_index(
        "ix_member_profiles_peak_status",
        "member_profiles",
        ["peak_id", "membership_status"],
        unique=False,
    )

    # ------------------------------------------------------------------ 用户/角色字段
    op.add_column(
        "users",
        sa.Column(
            "authorization_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "show_wallet_on_leaderboard",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.add_column(
        "roles", sa.Column("fantasy_display_name", sa.String(length=100), nullable=True)
    )
    op.add_column("roles", sa.Column("audit_domains", sa.JSON(), nullable=True))

    # ------------------------------------------------------------------ user_roles 作用范围
    op.execute("CREATE SEQUENCE IF NOT EXISTS user_roles_id_seq")
    op.add_column("user_roles", sa.Column("id", sa.Integer(), nullable=True))
    op.execute("UPDATE user_roles SET id = nextval('user_roles_id_seq')")
    op.execute("ALTER SEQUENCE user_roles_id_seq OWNED BY user_roles.id")
    op.execute("ALTER TABLE user_roles ALTER COLUMN id SET NOT NULL")
    op.execute(
        "ALTER TABLE user_roles ALTER COLUMN id "
        "SET DEFAULT nextval('user_roles_id_seq')"
    )
    op.execute("ALTER TABLE user_roles DROP CONSTRAINT IF EXISTS user_roles_pkey")
    op.create_primary_key("user_roles_pkey", "user_roles", ["id"])

    op.add_column(
        "user_roles",
        sa.Column(
            "scope_type", sa.String(length=10), nullable=False, server_default="own"
        ),
    )
    op.add_column(
        "user_roles", sa.Column("scope_peak_id", sa.BigInteger(), nullable=True)
    )
    op.add_column("user_roles", sa.Column("created_by", sa.Integer(), nullable=True))
    op.add_column(
        "user_roles",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_foreign_key(
        "fk_user_roles_scope_peak_id_peaks",
        "user_roles",
        "peaks",
        ["scope_peak_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_user_roles_created_by_users",
        "user_roles",
        "users",
        ["created_by"],
        ["id"],
    )

    # 既有绑定：admin 保留 all，其余回退最小权限 own
    op.execute(
        """
        UPDATE user_roles ur
        SET scope_type = CASE WHEN r.name = 'admin' THEN 'all' ELSE 'own' END
        FROM roles r
        WHERE r.id = ur.role_id
        """
    )

    op.create_check_constraint(
        "ck_user_roles_scope",
        "user_roles",
        "scope_type IN ('own', 'peak', 'all')",
    )
    op.create_check_constraint(
        "ck_user_roles_scope_peak",
        "user_roles",
        "(scope_type = 'peak' AND scope_peak_id IS NOT NULL) "
        "OR (scope_type <> 'peak' AND scope_peak_id IS NULL)",
    )

    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"], unique=False)
    op.create_index("ix_user_roles_scope_peak_id", "user_roles", ["scope_peak_id"], unique=False)
    op.create_index(
        "uq_user_roles_scope_own_all",
        "user_roles",
        ["user_id", "role_id", "scope_type"],
        unique=True,
        postgresql_where=sa.text("scope_type IN ('own', 'all')"),
    )
    op.create_index(
        "uq_user_roles_scope_peak",
        "user_roles",
        ["user_id", "role_id", "scope_peak_id"],
        unique=True,
        postgresql_where=sa.text("scope_type = 'peak'"),
    )

    # 普通用户角色统一命名为 member（保留既有绑定）
    op.execute(
        """
        UPDATE roles SET name = 'member'
        WHERE name = 'user'
          AND NOT EXISTS (SELECT 1 FROM roles WHERE name = 'member')
        """
    )


def downgrade() -> None:
    op.execute("UPDATE roles SET name = 'user' WHERE name = 'member'")

    op.drop_index("uq_user_roles_scope_peak", table_name="user_roles")
    op.drop_index("uq_user_roles_scope_own_all", table_name="user_roles")
    op.drop_index("ix_user_roles_scope_peak_id", table_name="user_roles")
    op.drop_index("ix_user_roles_user_id", table_name="user_roles")
    op.drop_constraint("ck_user_roles_scope_peak", "user_roles", type_="check")
    op.drop_constraint("ck_user_roles_scope", "user_roles", type_="check")
    op.drop_constraint("fk_user_roles_created_by_users", "user_roles", type_="foreignkey")
    op.drop_constraint("fk_user_roles_scope_peak_id_peaks", "user_roles", type_="foreignkey")
    op.drop_column("user_roles", "created_at")
    op.drop_column("user_roles", "created_by")
    op.drop_column("user_roles", "scope_peak_id")
    op.drop_column("user_roles", "scope_type")

    op.execute("ALTER TABLE user_roles DROP CONSTRAINT IF EXISTS user_roles_pkey")
    op.drop_column("user_roles", "id")
    op.create_primary_key("user_roles_pkey", "user_roles", ["user_id", "role_id"])
    op.execute("DROP SEQUENCE IF EXISTS user_roles_id_seq")

    op.drop_column("roles", "audit_domains")
    op.drop_column("roles", "fantasy_display_name")
    op.drop_column("users", "show_wallet_on_leaderboard")
    op.drop_column("users", "authorization_version")

    op.drop_index("ix_member_profiles_peak_status", table_name="member_profiles")
    op.drop_index("uq_member_profiles_student_id", table_name="member_profiles")
    op.drop_table("member_profiles")
    op.drop_index("ix_peaks_active_archived", table_name="peaks")
    op.drop_table("peaks")
