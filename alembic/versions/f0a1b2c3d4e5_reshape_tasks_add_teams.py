"""reshape tasks, add teams / submissions / task actions

Revision ID: f0a1b2c3d4e5
Revises: d5e6f7a8b9c0
Create Date: 2026-11-04

P3：任务改为单执行实例 + 团队快照；旧任务历史不导入，旧认领记录统一置为
cancelled，避免与新「每任务最多一个非取消实例」的部分唯一索引冲突。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------------------------------------------------------- 团队
    op.create_table(
        "teams",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("captain_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('forming', 'active', 'archived')", name="ck_teams_status"
        ),
        sa.ForeignKeyConstraint(["captain_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_teams_captain", "teams", ["captain_user_id"])
    op.create_index("ix_teams_status_created", "teams", ["status", "created_at", "id"])

    op.create_table(
        "team_members",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('captain', 'member')", name="ck_team_members_role"),
        sa.CheckConstraint(
            "status IN ('active', 'left')", name="ck_team_members_status"
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_team_members_active_user",
        "team_members",
        ["team_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_team_members_active_captain",
        "team_members",
        ["team_id"],
        unique=True,
        postgresql_where=sa.text("role = 'captain' AND status = 'active'"),
    )
    op.create_index("ix_team_members_user", "team_members", ["user_id", "id"])

    op.create_table(
        "team_invitations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("invitee_user_id", sa.Integer(), nullable=False),
        sa.Column("inviter_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'expired', 'cancelled')",
            name="ck_team_invitations_status",
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["invitee_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["inviter_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_team_invitations_pending",
        "team_invitations",
        ["team_id", "invitee_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_team_invitations_invitee", "team_invitations", ["invitee_user_id", "status"]
    )
    op.create_index(
        "ix_team_invitations_expires", "team_invitations", ["expires_at", "status"]
    )

    # ---------------------------------------------------------------- tasks
    op.drop_index("ix_tasks_created_by", table_name="tasks")
    op.drop_constraint("fk_tasks_created_by_users", "tasks", type_="foreignkey")
    op.alter_column("tasks", "created_by", new_column_name="publisher_id")
    op.create_foreign_key(
        "fk_tasks_publisher_id_users", "tasks", "users", ["publisher_id"], ["id"]
    )
    op.drop_column("tasks", "points")
    op.drop_column("tasks", "max_claimants")
    op.add_column("tasks", sa.Column("difficulty", sa.String(length=20), nullable=True))
    op.add_column(
        "tasks",
        sa.Column(
            "execution_mode",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'single'"),
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "reward_total",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("10"),
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "max_members", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "visibility",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'members'"),
        ),
    )
    op.add_column("tasks", sa.Column("peak_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "tasks", sa.Column("deadline", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "tasks",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "review_cycle", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "tasks", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "tasks", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_tasks_peak_id_peaks",
        "tasks",
        "peaks",
        ["peak_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_tasks_reward_positive", "tasks", "reward_total >= 1"
    )
    op.create_check_constraint(
        "ck_tasks_execution_mode", "tasks", "execution_mode IN ('single', 'team')"
    )
    op.create_check_constraint(
        "ck_tasks_member_count",
        "tasks",
        "(execution_mode = 'single' AND max_members = 1) "
        "OR (execution_mode = 'team' AND max_members >= 2)",
    )
    op.create_check_constraint(
        "ck_tasks_visibility", "tasks", "visibility IN ('public', 'members', 'peak')"
    )
    op.create_check_constraint(
        "ck_tasks_peak_visibility", "tasks", "visibility <> 'peak' OR peak_id IS NOT NULL"
    )
    op.create_index("ix_tasks_status_deadline", "tasks", ["status", "deadline", "id"])
    op.create_index(
        "ix_tasks_publisher_created", "tasks", ["publisher_id", "created_at", "id"]
    )
    op.create_index("ix_tasks_peak_status", "tasks", ["peak_id", "status", "id"])

    # ---------------------------------------------------------- task_claims
    # 旧认领记录不进入新状态机：统一标记取消，避免与新部分唯一索引冲突。
    op.execute(
        "UPDATE task_claims SET status = 'cancelled' WHERE status <> 'cancelled'"
    )
    op.add_column("task_claims", sa.Column("team_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "task_claims", sa.Column("leader_user_id", sa.Integer(), nullable=True)
    )
    op.execute("UPDATE task_claims SET leader_user_id = user_id")
    op.alter_column("task_claims", "leader_user_id", nullable=False)
    op.add_column(
        "task_claims", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE task_claims SET started_at = created_at")
    op.alter_column("task_claims", "started_at", nullable=False)
    op.add_column(
        "task_claims",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "task_claims",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.drop_constraint("ux_task_claims_unique", "task_claims", type_="unique")
    op.drop_index("ix_task_claims_task_id", table_name="task_claims")
    op.drop_index("ix_task_claims_user_id", table_name="task_claims")
    op.drop_index("ix_task_claims_status", table_name="task_claims")
    op.drop_constraint(
        "fk_task_claims_user_id_users", "task_claims", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_task_claims_reviewed_by_users", "task_claims", type_="foreignkey"
    )
    op.drop_column("task_claims", "user_id")
    op.drop_column("task_claims", "claim_note")
    op.drop_column("task_claims", "reviewed_by")
    op.drop_column("task_claims", "review_note")
    op.create_foreign_key(
        "fk_task_claims_team_id_teams", "task_claims", "teams", ["team_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_task_claims_leader_user_id_users",
        "task_claims",
        "users",
        ["leader_user_id"],
        ["id"],
    )
    op.create_index("ix_task_claims_task_id", "task_claims", ["task_id"])
    op.create_index("ix_task_claims_status", "task_claims", ["status"])
    op.create_index("ix_task_claims_leader", "task_claims", ["leader_user_id"])
    op.create_index(
        "ix_task_claims_status_started", "task_claims", ["status", "started_at"]
    )
    op.create_index(
        "uq_task_claims_open_task",
        "task_claims",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'submitted', 'completed')"),
    )
    op.create_index(
        "uq_task_claims_open_team",
        "task_claims",
        ["team_id"],
        unique=True,
        postgresql_where=sa.text(
            "team_id IS NOT NULL AND status IN ('active', 'submitted')"
        ),
    )

    # ---------------------------------------------------- 执行快照 / 成果 / 历史
    op.create_table(
        "task_claim_members",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("claim_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "is_leader", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["task_claims.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "claim_id", "user_id", name="uq_task_claim_members_claim_user"
        ),
    )
    op.create_index(
        "uq_task_claim_members_leader",
        "task_claim_members",
        ["claim_id"],
        unique=True,
        postgresql_where=sa.text("is_leader"),
    )
    op.create_index(
        "ix_task_claim_members_user", "task_claim_members", ["user_id", "id"]
    )

    op.create_table(
        "task_submissions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("claim_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attachments", sa.JSON(), nullable=True),
        sa.Column("submitted_by", sa.Integer(), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["claim_id"], ["task_claims.id"]),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "claim_id", "revision", name="uq_task_submissions_claim_revision"
        ),
    )
    op.create_index(
        "uq_task_submissions_pending",
        "task_submissions",
        ["claim_id"],
        unique=True,
        postgresql_where=sa.text("review_status = 'pending'"),
    )
    op.create_index("ix_task_submissions_claim_id", "task_submissions", ["claim_id", "id"])

    op.create_table(
        "task_actions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["claim_id"], ["task_claims.id"]),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_actions_task_id", "task_actions", ["task_id", "id"])
    op.create_index("ix_task_actions_claim_id", "task_actions", ["claim_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_task_actions_claim_id", table_name="task_actions")
    op.drop_index("ix_task_actions_task_id", table_name="task_actions")
    op.drop_table("task_actions")

    op.drop_index("ix_task_submissions_claim_id", table_name="task_submissions")
    op.drop_index("uq_task_submissions_pending", table_name="task_submissions")
    op.drop_table("task_submissions")

    op.drop_index("ix_task_claim_members_user", table_name="task_claim_members")
    op.drop_index("uq_task_claim_members_leader", table_name="task_claim_members")
    op.drop_table("task_claim_members")

    op.drop_index("uq_task_claims_open_team", table_name="task_claims")
    op.drop_index("uq_task_claims_open_task", table_name="task_claims")
    op.drop_index("ix_task_claims_status_started", table_name="task_claims")
    op.drop_index("ix_task_claims_leader", table_name="task_claims")
    op.drop_index("ix_task_claims_status", table_name="task_claims")
    op.drop_index("ix_task_claims_task_id", table_name="task_claims")
    op.drop_constraint(
        "fk_task_claims_leader_user_id_users", "task_claims", type_="foreignkey"
    )
    op.drop_constraint("fk_task_claims_team_id_teams", "task_claims", type_="foreignkey")
    op.add_column(
        "task_claims", sa.Column("user_id", sa.Integer(), nullable=True)
    )
    op.execute("UPDATE task_claims SET user_id = leader_user_id")
    op.alter_column("task_claims", "user_id", nullable=False)
    op.add_column("task_claims", sa.Column("claim_note", sa.Text(), nullable=True))
    op.add_column(
        "task_claims", sa.Column("reviewed_by", sa.Integer(), nullable=True)
    )
    op.add_column("task_claims", sa.Column("review_note", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_task_claims_user_id_users", "task_claims", "users", ["user_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_task_claims_reviewed_by_users",
        "task_claims",
        "users",
        ["reviewed_by"],
        ["id"],
    )
    op.create_unique_constraint(
        "ux_task_claims_unique", "task_claims", ["task_id", "user_id"]
    )
    op.create_index("ix_task_claims_task_id", "task_claims", ["task_id"])
    op.create_index("ix_task_claims_user_id", "task_claims", ["user_id"])
    op.create_index("ix_task_claims_status", "task_claims", ["status"])
    op.drop_column("task_claims", "updated_at")
    op.drop_column("task_claims", "version")
    op.drop_column("task_claims", "started_at")
    op.drop_column("task_claims", "leader_user_id")
    op.drop_column("task_claims", "team_id")

    op.drop_index("ix_tasks_peak_status", table_name="tasks")
    op.drop_index("ix_tasks_publisher_created", table_name="tasks")
    op.drop_index("ix_tasks_status_deadline", table_name="tasks")
    op.drop_constraint("ck_tasks_peak_visibility", "tasks", type_="check")
    op.drop_constraint("ck_tasks_visibility", "tasks", type_="check")
    op.drop_constraint("ck_tasks_member_count", "tasks", type_="check")
    op.drop_constraint("ck_tasks_execution_mode", "tasks", type_="check")
    op.drop_constraint("ck_tasks_reward_positive", "tasks", type_="check")
    op.drop_constraint("fk_tasks_peak_id_peaks", "tasks", type_="foreignkey")
    op.drop_column("tasks", "archived_at")
    op.drop_column("tasks", "reviewed_at")
    op.drop_column("tasks", "review_cycle")
    op.drop_column("tasks", "version")
    op.drop_column("tasks", "deadline")
    op.drop_column("tasks", "peak_id")
    op.drop_column("tasks", "visibility")
    op.drop_column("tasks", "max_members")
    op.drop_column("tasks", "reward_total")
    op.drop_column("tasks", "execution_mode")
    op.drop_column("tasks", "difficulty")
    op.add_column(
        "tasks",
        sa.Column(
            "points", sa.Integer(), nullable=False, server_default=sa.text("10")
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "max_claimants", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
    )
    op.drop_constraint("fk_tasks_publisher_id_users", "tasks", type_="foreignkey")
    op.alter_column("tasks", "publisher_id", new_column_name="created_by")
    op.create_foreign_key(
        "fk_tasks_created_by_users", "tasks", "users", ["created_by"], ["id"]
    )
    op.create_index("ix_tasks_created_by", "tasks", ["created_by"])

    op.drop_index("ix_team_invitations_expires", table_name="team_invitations")
    op.drop_index("ix_team_invitations_invitee", table_name="team_invitations")
    op.drop_index("uq_team_invitations_pending", table_name="team_invitations")
    op.drop_table("team_invitations")
    op.drop_index("ix_team_members_user", table_name="team_members")
    op.drop_index("uq_team_members_active_captain", table_name="team_members")
    op.drop_index("uq_team_members_active_user", table_name="team_members")
    op.drop_table("team_members")
    op.drop_index("ix_teams_status_created", table_name="teams")
    op.drop_index("ix_teams_captain", table_name="teams")
    op.drop_table("teams")
