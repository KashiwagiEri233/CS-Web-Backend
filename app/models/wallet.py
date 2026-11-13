"""统一钱包与复式账本模型（P2）。

设计要点：
- 同一货币的不同账户（个人/峰/总库/任务托管/发行对手），不是多套账本。
- 金额为 BIGINT 最小单位，服务层只接受正整数金额；JSON 传输由 schema 输出字符串。
- 交易与分录一旦写入不可修改/删除；错误通过反向交易处理。
- 账户余额是服务维护的投影，由同事务分录更新，不提供直接改余额的 API。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime as _DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)

# 账户类型
ACCOUNT_KIND_USER = "user"
ACCOUNT_KIND_PEAK = "peak"
ACCOUNT_KIND_TREASURY = "treasury"
ACCOUNT_KIND_TASK_ESCROW = "task_escrow"
ACCOUNT_KIND_ISSUANCE = "issuance"
ACCOUNT_KINDS = (
    ACCOUNT_KIND_USER,
    ACCOUNT_KIND_PEAK,
    ACCOUNT_KIND_TREASURY,
    ACCOUNT_KIND_TASK_ESCROW,
    ACCOUNT_KIND_ISSUANCE,
)


class WalletAccount(Base):
    """资金账户：每用户/峰/任务一个；总库与发行对手各唯一。"""

    __tablename__ = "wallet_accounts"
    __table_args__ = (
        CheckConstraint(
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
        CheckConstraint(
            "kind IN ('user', 'peak', 'treasury', 'task_escrow', 'issuance')",
            name="ck_wallet_accounts_kind",
        ),
        # 非发行账户余额不得为负；发行对手账户允许负数（复式记账对手）
        CheckConstraint(
            "kind = 'issuance' OR balance >= 0",
            name="ck_wallet_accounts_balance",
        ),
        Index(
            "uq_wallet_accounts_user",
            "owner_user_id",
            unique=True,
            postgresql_where=text("kind = 'user'"),
        ),
        Index(
            "uq_wallet_accounts_peak",
            "owner_peak_id",
            unique=True,
            postgresql_where=text("kind = 'peak'"),
        ),
        Index(
            "uq_wallet_accounts_task",
            "owner_task_id",
            unique=True,
            postgresql_where=text("kind = 'task_escrow'"),
        ),
        Index(
            "uq_wallet_accounts_treasury",
            "kind",
            unique=True,
            postgresql_where=text("kind = 'treasury'"),
        ),
        Index(
            "uq_wallet_accounts_issuance",
            "kind",
            unique=True,
            postgresql_where=text("kind = 'issuance'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    owner_peak_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("peaks.id"), nullable=True
    )
    owner_task_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tasks.id"), nullable=True
    )
    balance: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return f"<WalletAccount(id={self.id}, kind='{self.kind}', balance={self.balance})>"


class LedgerTransaction(Base):
    """复式交易头：一组平衡分录；封账后不可修改。"""

    __tablename__ = "ledger_transactions"
    __table_args__ = (
        UniqueConstraint("business_key", name="uq_ledger_transactions_business_key"),
        Index(
            "uq_ledger_transactions_original",
            "original_transaction_id",
            unique=True,
            postgresql_where=text("original_transaction_id IS NOT NULL"),
        ),
        Index("ix_ledger_transactions_type_created", "type", "created_at"),
        Index("ix_ledger_transactions_related_task", "related_task_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    business_key: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    source_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    related_task_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    original_transaction_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("ledger_transactions.id"), nullable=True
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # 仅用于同事务内组装分录：插入→分录→封账→提交；未封账交易不允许提交
    is_sealed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class LedgerEntry(Base):
    """分录：一笔交易内至少两条；delta 非零，和为零。"""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint(
            "transaction_id", "entry_no", name="uq_ledger_entries_tx_entry_no"
        ),
        CheckConstraint("delta <> 0", name="ck_ledger_entries_delta_nonzero"),
        Index("ix_ledger_entries_account_id", "account_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    transaction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ledger_transactions.id"), nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("wallet_accounts.id"), nullable=False
    )
    delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_no: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class IdempotencyRecord(Base):
    """写动作幂等记录：同键同内容返回原结果，同键异内容 409。"""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "actor_id", "operation", "key", name="uq_idempotency_actor_operation_key"
        ),
        Index("ix_idempotency_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    canonical_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[Optional[dict]] = mapped_column(
        JSONDict, nullable=True, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ReconciliationRun(Base):
    """对账运行报告：只保存状态与脱敏差异摘要，不另存可变余额。"""

    __tablename__ = "reconciliation_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running", index=True
    )
    counts: Mapped[Optional[dict]] = mapped_column(JSONDict, nullable=True, default=dict)
    differences: Mapped[Optional[dict]] = mapped_column(
        JSONDict, nullable=True, default=dict
    )
    triggered_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
