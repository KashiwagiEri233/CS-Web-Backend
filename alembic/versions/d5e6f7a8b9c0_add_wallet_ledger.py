"""add unified wallet accounts and double-entry ledger

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-11-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wallet_accounts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("owner_peak_id", sa.BigInteger(), nullable=True),
        sa.Column("owner_task_id", sa.Integer(), nullable=True),
        sa.Column(
            "balance", sa.BigInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
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
        sa.CheckConstraint(
            "(kind = 'user' AND owner_user_id IS NOT NULL "
            "AND owner_peak_id IS NULL AND owner_task_id IS NULL) "
            "OR (kind = 'peak' AND owner_peak_id IS NOT NULL "
            "AND owner_user_id IS NULL AND owner_task_id IS NULL) "
            "OR (kind = 'task_escrow' AND owner_task_id IS NOT NULL "
            "AND owner_user_id IS NULL AND owner_peak_id IS NULL) "
            "OR (kind IN ('treasury', 'issuance') AND owner_user_id IS NULL "
            "AND owner_peak_id IS NULL AND owner_task_id IS NULL)",
            name="ck_wallet_accounts_owner",
        ),
        sa.CheckConstraint(
            "kind IN ('user', 'peak', 'treasury', 'task_escrow', 'issuance')",
            name="ck_wallet_accounts_kind",
        ),
        sa.CheckConstraint(
            "kind = 'issuance' OR balance >= 0", name="ck_wallet_accounts_balance"
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["owner_peak_id"], ["peaks.id"]),
        sa.ForeignKeyConstraint(["owner_task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wallet_accounts_kind", "wallet_accounts", ["kind"], unique=False)
    op.create_index(
        "uq_wallet_accounts_user",
        "wallet_accounts",
        ["owner_user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'user'"),
    )
    op.create_index(
        "uq_wallet_accounts_peak",
        "wallet_accounts",
        ["owner_peak_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'peak'"),
    )
    op.create_index(
        "uq_wallet_accounts_task",
        "wallet_accounts",
        ["owner_task_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'task_escrow'"),
    )
    op.create_index(
        "uq_wallet_accounts_treasury",
        "wallet_accounts",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("kind = 'treasury'"),
    )
    op.create_index(
        "uq_wallet_accounts_issuance",
        "wallet_accounts",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("kind = 'issuance'"),
    )

    op.create_table(
        "ledger_transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("business_key", sa.String(length=120), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=30), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("related_task_id", sa.Integer(), nullable=True),
        sa.Column("original_transaction_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "is_sealed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["original_transaction_id"], ["ledger_transactions.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_key", name="uq_ledger_transactions_business_key"),
    )
    op.create_index(
        "uq_ledger_transactions_original",
        "ledger_transactions",
        ["original_transaction_id"],
        unique=True,
        postgresql_where=sa.text("original_transaction_id IS NOT NULL"),
    )
    op.create_index(
        "ix_ledger_transactions_type_created",
        "ledger_transactions",
        ["type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ledger_transactions_related_task",
        "ledger_transactions",
        ["related_task_id"],
        unique=False,
    )

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("transaction_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("delta", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("entry_no", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("delta <> 0", name="ck_ledger_entries_delta_nonzero"),
        sa.ForeignKeyConstraint(["account_id"], ["wallet_accounts.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["ledger_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "transaction_id", "entry_no", name="uq_ledger_entries_tx_entry_no"
        ),
    )
    op.create_index(
        "ix_ledger_entries_account_id",
        "ledger_entries",
        ["account_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_ledger_entries_transaction_id",
        "ledger_entries",
        ["transaction_id"],
        unique=False,
    )

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=50), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("canonical_request_hash", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_id", "operation", "key", name="uq_idempotency_actor_operation_key"
        ),
    )
    op.create_index(
        "ix_idempotency_expires_at",
        "idempotency_records",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "reconciliation_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column("counts", sa.JSON(), nullable=True),
        sa.Column("differences", sa.JSON(), nullable=True),
        sa.Column("triggered_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reconciliation_runs_status", "reconciliation_runs", ["status"], unique=False
    )

    # ---------------------------------------------------------------- 账本不变量触发器
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_ledger_entry_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'ledger entries are immutable';
        END $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_ledger_entries_immutable
        BEFORE UPDATE OR DELETE ON ledger_entries
        FOR EACH ROW EXECUTE FUNCTION prevent_ledger_entry_mutation();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION check_ledger_entry_insert() RETURNS trigger AS $$
        DECLARE sealed boolean;
        BEGIN
          SELECT is_sealed INTO sealed FROM ledger_transactions WHERE id = NEW.transaction_id;
          IF sealed IS NULL THEN
            RAISE EXCEPTION 'ledger transaction % not found', NEW.transaction_id;
          END IF;
          IF sealed THEN
            RAISE EXCEPTION 'ledger transaction % is already sealed', NEW.transaction_id;
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_ledger_entries_insert_guard
        BEFORE INSERT ON ledger_entries
        FOR EACH ROW EXECUTE FUNCTION check_ledger_entry_insert();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_sealed_transaction_change() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'ledger transactions cannot be deleted';
          END IF;
          IF OLD.is_sealed THEN
            RAISE EXCEPTION 'sealed ledger transaction % is immutable', OLD.id;
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_ledger_transactions_immutable
        BEFORE UPDATE OR DELETE ON ledger_transactions
        FOR EACH ROW EXECUTE FUNCTION prevent_sealed_transaction_change();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION check_ledger_transaction_balanced() RETURNS trigger AS $$
        DECLARE sealed boolean;
        DECLARE entry_count integer;
        DECLARE total bigint;
        BEGIN
          SELECT is_sealed INTO sealed FROM ledger_transactions WHERE id = NEW.id;
          IF sealed IS NOT TRUE THEN
            RAISE EXCEPTION 'ledger transaction % is not sealed at commit', NEW.id;
          END IF;
          SELECT count(*), COALESCE(sum(delta), 0) INTO entry_count, total
          FROM ledger_entries WHERE transaction_id = NEW.id;
          IF entry_count < 2 THEN
            RAISE EXCEPTION 'ledger transaction % requires at least 2 entries', NEW.id;
          END IF;
          IF total <> 0 THEN
            RAISE EXCEPTION 'ledger transaction % is unbalanced: sum=%', NEW.id, total;
          END IF;
          RETURN NULL;
        END $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_ledger_transactions_balanced
        AFTER INSERT OR UPDATE ON ledger_transactions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION check_ledger_transaction_balanced();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_ledger_transactions_balanced ON ledger_transactions")
    op.execute("DROP FUNCTION IF EXISTS check_ledger_transaction_balanced()")
    op.execute("DROP TRIGGER IF EXISTS trg_ledger_transactions_immutable ON ledger_transactions")
    op.execute("DROP FUNCTION IF EXISTS prevent_sealed_transaction_change()")
    op.execute("DROP TRIGGER IF EXISTS trg_ledger_entries_insert_guard ON ledger_entries")
    op.execute("DROP FUNCTION IF EXISTS check_ledger_entry_insert()")
    op.execute("DROP TRIGGER IF EXISTS trg_ledger_entries_immutable ON ledger_entries")
    op.execute("DROP FUNCTION IF EXISTS prevent_ledger_entry_mutation()")

    op.drop_index("ix_reconciliation_runs_status", table_name="reconciliation_runs")
    op.drop_table("reconciliation_runs")
    op.drop_index("ix_idempotency_expires_at", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_ledger_entries_transaction_id", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_account_id", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_index("ix_ledger_transactions_related_task", table_name="ledger_transactions")
    op.drop_index("ix_ledger_transactions_type_created", table_name="ledger_transactions")
    op.drop_index("uq_ledger_transactions_original", table_name="ledger_transactions")
    op.drop_table("ledger_transactions")
    for index_name in (
        "uq_wallet_accounts_issuance",
        "uq_wallet_accounts_treasury",
        "uq_wallet_accounts_task",
        "uq_wallet_accounts_peak",
        "uq_wallet_accounts_user",
        "ix_wallet_accounts_kind",
    ):
        op.drop_index(index_name, table_name="wallet_accounts")
    op.drop_table("wallet_accounts")
