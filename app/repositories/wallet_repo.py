"""钱包/账本数据访问层：只 flush，不 commit。"""

from __future__ import annotations

from typing import List, Optional, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.models.wallet import (
    ACCOUNT_KIND_ISSUANCE,
    ACCOUNT_KIND_TREASURY,
    IdempotencyRecord,
    LedgerEntry,
    LedgerTransaction,
    ReconciliationRun,
    WalletAccount,
)
from app.repositories.base import paginate


class WalletRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_account(self, user_id: int) -> Optional[WalletAccount]:
        result = await self.db.execute(
            select(WalletAccount).where(
                WalletAccount.kind == "user", WalletAccount.owner_user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def get_system_account(self, kind: str) -> Optional[WalletAccount]:
        result = await self.db.execute(
            select(WalletAccount).where(WalletAccount.kind == kind)
        )
        return result.scalar_one_or_none()

    async def ensure_user_account(self, user_id: int) -> WalletAccount:
        """幂等创建用户账户（并发靠部分唯一索引 + ON CONFLICT 串行化）。"""
        await self.db.execute(
            pg_insert(WalletAccount)
            .values(
                kind="user", owner_user_id=user_id, balance=0, is_active=True
            )
            .on_conflict_do_nothing(
                index_elements=["owner_user_id"], index_where=text("kind = 'user'")
            )
        )
        await self.db.flush()
        account = await self.get_user_account(user_id)
        if account is None:
            raise RuntimeError(f"用户账户创建失败: user_id={user_id}")
        return account

    async def ensure_system_accounts(self) -> tuple[WalletAccount, WalletAccount]:
        """确保总库与发行对手账户存在且各唯一。"""
        treasury = await self.get_system_account(ACCOUNT_KIND_TREASURY)
        if treasury is None:
            await self.db.execute(
                pg_insert(WalletAccount)
                .values(kind=ACCOUNT_KIND_TREASURY, balance=0, is_active=True)
                .on_conflict_do_nothing(
                    index_elements=["kind"], index_where=text("kind = 'treasury'")
                )
            )
            await self.db.flush()
            treasury = await self.get_system_account(ACCOUNT_KIND_TREASURY)
        issuance = await self.get_system_account(ACCOUNT_KIND_ISSUANCE)
        if issuance is None:
            await self.db.execute(
                pg_insert(WalletAccount)
                .values(kind=ACCOUNT_KIND_ISSUANCE, balance=0, is_active=True)
                .on_conflict_do_nothing(
                    index_elements=["kind"], index_where=text("kind = 'issuance'")
                )
            )
            await self.db.flush()
            issuance = await self.get_system_account(ACCOUNT_KIND_ISSUANCE)
        if treasury is None or issuance is None:
            raise RuntimeError("系统账户初始化失败")
        return treasury, issuance

    async def get_peak_account(self, peak_id: int) -> Optional[WalletAccount]:
        result = await self.db.execute(
            select(WalletAccount).where(
                WalletAccount.kind == "peak",
                WalletAccount.owner_peak_id == peak_id,
            )
        )
        return result.scalar_one_or_none()

    async def ensure_peak_account(self, peak_id: int) -> WalletAccount:
        """幂等创建峰组织账户（零余额）。"""
        await self.db.execute(
            pg_insert(WalletAccount)
            .values(kind="peak", owner_peak_id=peak_id, balance=0, is_active=True)
            .on_conflict_do_nothing(
                index_elements=["owner_peak_id"], index_where=text("kind = 'peak'")
            )
        )
        await self.db.flush()
        result = await self.db.execute(
            select(WalletAccount).where(
                WalletAccount.kind == "peak",
                WalletAccount.owner_peak_id == peak_id,
            )
        )
        account = result.scalar_one_or_none()
        if account is None:
            raise RuntimeError(f"峰账户创建失败: peak_id={peak_id}")
        return account

    async def ensure_task_escrow(self, task_id: int) -> WalletAccount:
        """幂等创建任务托管账户（零余额）。"""
        await self.db.execute(
            pg_insert(WalletAccount)
            .values(kind="task_escrow", owner_task_id=task_id, balance=0, is_active=True)
            .on_conflict_do_nothing(
                index_elements=["owner_task_id"],
                index_where=text("kind = 'task_escrow'"),
            )
        )
        await self.db.flush()
        result = await self.db.execute(
            select(WalletAccount).where(
                WalletAccount.kind == "task_escrow",
                WalletAccount.owner_task_id == task_id,
            )
        )
        account = result.scalar_one_or_none()
        if account is None:
            raise RuntimeError(f"任务托管账户创建失败: task_id={task_id}")
        return account

    async def lock_accounts(self, account_ids: Sequence[int]) -> List[WalletAccount]:
        """按 account_id 升序加行锁，避免转账死锁。"""
        if not account_ids:
            return []
        ordered = sorted(set(account_ids))
        result = await self.db.execute(
            select(WalletAccount)
            .where(WalletAccount.id.in_(ordered))
            .order_by(WalletAccount.id)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def get_account_by_id(self, account_id: int) -> Optional[WalletAccount]:
        result = await self.db.execute(
            select(WalletAccount).where(WalletAccount.id == account_id)
        )
        return result.scalar_one_or_none()

    async def create_transaction(self, data: dict) -> LedgerTransaction:
        tx = LedgerTransaction(**data)
        self.db.add(tx)
        await self.db.flush()
        await self.db.refresh(tx)
        return tx

    async def add_entries(self, entries: Sequence[dict]) -> None:
        if not entries:
            return
        self.db.add_all([LedgerEntry(**item) for item in entries])
        await self.db.flush()

    async def seal_transaction(self, tx: LedgerTransaction) -> None:
        tx.is_sealed = True
        self.db.add(tx)
        await self.db.flush()

    async def get_transaction(self, transaction_id: int) -> Optional[LedgerTransaction]:
        result = await self.db.execute(
            select(LedgerTransaction).where(LedgerTransaction.id == transaction_id)
        )
        return result.scalar_one_or_none()

    async def get_transaction_by_business_key(
        self, business_key: str
    ) -> Optional[LedgerTransaction]:
        result = await self.db.execute(
            select(LedgerTransaction).where(
                LedgerTransaction.business_key == business_key
            )
        )
        return result.scalar_one_or_none()

    async def get_entries(self, transaction_id: int) -> List[LedgerEntry]:
        result = await self.db.execute(
            select(LedgerEntry)
            .where(LedgerEntry.transaction_id == transaction_id)
            .order_by(LedgerEntry.entry_no)
        )
        return list(result.scalars().all())

    async def list_account_entries(
        self, account_id: int, skip: int, limit: int
    ) -> List[LedgerEntry]:
        result = await self.db.execute(
            paginate(
                select(LedgerEntry)
                .where(LedgerEntry.account_id == account_id)
                .order_by(LedgerEntry.id.desc()),
                skip,
                limit,
            )
        )
        return list(result.scalars().all())

    async def count_account_entries(self, account_id: int) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(LedgerEntry)
            .where(LedgerEntry.account_id == account_id)
        )
        return int(result.scalar_one())

    async def leaderboard(self, limit: int) -> List[tuple[User, WalletAccount]]:
        """公开余额排行：仅有效、未删除且已同意公开的用户。"""
        result = await self.db.execute(
            select(User, WalletAccount)
            .join(WalletAccount, WalletAccount.owner_user_id == User.id)
            .where(
                WalletAccount.kind == "user",
                User.show_wallet_on_leaderboard.is_(True),
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
            .order_by(WalletAccount.balance.desc(), User.id)
            .limit(limit)
        )
        return list(result.tuples().all())

    async def escrow_total_for_publisher(self, user_id: int) -> int:
        """发布者托管中汇总：其发布任务 escrow 账户余额之和。"""
        result = await self.db.execute(
            select(func.coalesce(func.sum(WalletAccount.balance), 0))
            .select_from(WalletAccount)
            .join(Task, Task.id == WalletAccount.owner_task_id)
            .where(
                WalletAccount.kind == "task_escrow", Task.publisher_id == user_id
            )
        )
        return int(result.scalar_one())

    async def get_idempotency_record(
        self, actor_id: int, operation: str, key: str
    ) -> Optional[IdempotencyRecord]:
        result = await self.db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.actor_id == actor_id,
                IdempotencyRecord.operation == operation,
                IdempotencyRecord.key == key,
            )
        )
        return result.scalar_one_or_none()

    async def create_idempotency_record(self, data: dict) -> IdempotencyRecord:
        record = IdempotencyRecord(**data)
        self.db.add(record)
        await self.db.flush()
        return record

    async def list_reconciliation_runs(
        self, skip: int, limit: int
    ) -> List[ReconciliationRun]:
        result = await self.db.execute(
            paginate(
                select(ReconciliationRun)
                .order_by(ReconciliationRun.id.desc()),
                skip,
                limit,
            )
        )
        return list(result.scalars().all())

    async def count_reconciliation_runs(self) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(ReconciliationRun)
        )
        return int(result.scalar_one())
