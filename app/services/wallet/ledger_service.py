"""复式账本内核：账户、锁定、平衡分录与封账。

事务约定：本 service 只 flush，不 commit；由调用方（钱包/任务/财务业务）在
同一外层事务提交，确保业务状态、资金分录、幂等结果与审计原子一致。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    ErrorCode,
    NotFoundException,
    ValidationException,
)
from app.models.wallet import ACCOUNT_KIND_ISSUANCE, LedgerTransaction, WalletAccount
from app.repositories.wallet_repo import WalletRepository

# 账户类型常量集中在此，避免调用方散落字符串魔法值
KIND_USER = "user"
KIND_PEAK = "peak"
KIND_TREASURY = "treasury"
KIND_TASK_ESCROW = "task_escrow"
KIND_ISSUANCE = ACCOUNT_KIND_ISSUANCE


class LedgerService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = WalletRepository(db)

    async def ensure_user_account(self, user_id: int) -> WalletAccount:
        """确保用户钱包存在（零余额），返回账户。"""
        return await self.repo.ensure_user_account(user_id)

    async def ensure_system_accounts(self) -> tuple[WalletAccount, WalletAccount]:
        """确保总库与发行对手账户存在。"""
        return await self.repo.ensure_system_accounts()

    async def get_summary(self, user_id: int) -> dict:
        account = await self.repo.ensure_user_account(user_id)
        escrow_total = await self.repo.escrow_total_for_publisher(user_id)
        return {
            "user_id": user_id,
            "account_id": account.id,
            "balance": int(account.balance),
            "escrow_total": int(escrow_total),
        }

    async def transfer(
        self,
        *,
        from_account_id: int,
        to_account_id: int,
        amount: int,
        type: str,
        business_key: str,
        actor_user_id: Optional[int] = None,
        reason: Optional[str] = None,
        related_task_id: Optional[int] = None,
        request_id: Optional[str] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
    ):
        """执行一笔两分录转账；返回已封账交易与分录。

        锁顺序：按 account_id 升序，避免相反方向并发转账死锁。
        金额必须为正整数；非发行账户余额不足整笔失败，不做部分扣款。
        """
        if amount <= 0:
            raise ValidationException(
                message="金额必须为正整数",
                error_code=ErrorCode.Validation.INVALID_MONEY_AMOUNT,
            )
        if from_account_id == to_account_id:
            raise ValidationException(
                message="转出与转入账户不能相同",
                error_code=ErrorCode.Validation.INVALID_MONEY_AMOUNT,
            )

        accounts = await self.repo.lock_accounts([from_account_id, to_account_id])
        by_id = {account.id: account for account in accounts}
        from_account = by_id.get(from_account_id)
        to_account = by_id.get(to_account_id)
        if from_account is None or to_account is None:
            raise ConflictException(message="资金账户不存在")
        if not from_account.is_active or not to_account.is_active:
            raise ConflictException(message="资金账户已停用")

        if from_account.kind != KIND_ISSUANCE and from_account.balance < amount:
            raise ConflictException(
                message="余额不足",
                error_code=ErrorCode.Conflict.INSUFFICIENT_BALANCE,
                details={"balance": int(from_account.balance), "amount": amount},
            )

        from_after = int(from_account.balance) - amount
        to_after = int(to_account.balance) + amount

        tx = await self.repo.create_transaction(
            {
                "type": type,
                "business_key": business_key,
                "actor_user_id": actor_user_id,
                "source_type": source_type,
                "source_id": source_id,
                "related_task_id": related_task_id,
                "reason": reason,
                "request_id": request_id,
                "is_sealed": False,
            }
        )
        await self.repo.add_entries(
            [
                {
                    "transaction_id": tx.id,
                    "account_id": from_account.id,
                    "delta": -amount,
                    "balance_after": from_after,
                    "entry_no": 1,
                },
                {
                    "transaction_id": tx.id,
                    "account_id": to_account.id,
                    "delta": amount,
                    "balance_after": to_after,
                    "entry_no": 2,
                },
            ]
        )

        from_account.balance = from_after
        from_account.version = (from_account.version or 1) + 1
        to_account.balance = to_after
        to_account.version = (to_account.version or 1) + 1
        self.db.add(from_account)
        self.db.add(to_account)
        await self.db.flush()

        await self.repo.seal_transaction(tx)
        entries = await self.repo.get_entries(tx.id)
        return tx, entries

    async def reverse(
        self,
        *,
        original_transaction_id: int,
        actor_user_id: Optional[int],
        reason: str,
        business_key: str,
        request_id: Optional[str] = None,
    ):
        """冲正一笔已封账交易：按原分录取反生成新交易。

        - 只允许冲正一次（``original_transaction_id`` 部分唯一索引兜底）；
        - 冲正交易本身不能再被冲正；
        - 反向扣款按余额校验，余额不足整笔失败，不做部分冲正。
        """
        original = await self.repo.get_transaction(original_transaction_id)
        if original is None:
            raise NotFoundException(
                message="原交易不存在",
                resource_type="ledger_transaction",
                resource_id=original_transaction_id,
            )
        if original.type == "reversal":
            raise ValidationException(message="冲正交易不能再被冲正")
        if not original.is_sealed:
            raise ConflictException(message="原交易未封账，不能冲正")

        existing = (
            await self.db.execute(
                select(LedgerTransaction.id).where(
                    LedgerTransaction.original_transaction_id == original.id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictException(message="该交易已冲正")

        entries = await self.repo.get_entries(original.id)
        if not entries:
            raise ConflictException(message="原交易没有分录，无法冲正")

        accounts = await self.repo.lock_accounts([entry.account_id for entry in entries])
        by_id = {account.id: account for account in accounts}
        for entry in entries:
            account = by_id.get(entry.account_id)
            if account is None:
                raise ConflictException(message="原交易分录账户不存在")
            if not account.is_active:
                raise ConflictException(message="资金账户已停用，不能冲正")

        for entry in entries:
            account = by_id[entry.account_id]
            reversed_delta = -int(entry.delta)
            if (
                reversed_delta < 0
                and account.kind != KIND_ISSUANCE
                and int(account.balance) + reversed_delta < 0
            ):
                raise ConflictException(
                    message="余额不足，无法冲正",
                    error_code=ErrorCode.Conflict.INSUFFICIENT_BALANCE,
                    details={"account_id": account.id, "balance": int(account.balance)},
                )

        tx = await self.repo.create_transaction(
            {
                "type": "reversal",
                "business_key": business_key,
                "actor_user_id": actor_user_id,
                "original_transaction_id": original.id,
                "reason": reason,
                "request_id": request_id,
                "is_sealed": False,
            }
        )

        reversed_entries = []
        for entry_no, entry in enumerate(entries, start=1):
            account = by_id[entry.account_id]
            delta = -int(entry.delta)
            after = int(account.balance) + delta
            account.balance = after
            account.version = (account.version or 1) + 1
            self.db.add(account)
            reversed_entries.append(
                {
                    "transaction_id": tx.id,
                    "account_id": account.id,
                    "delta": delta,
                    "balance_after": after,
                    "entry_no": entry_no,
                }
            )

        await self.repo.add_entries(reversed_entries)
        await self.db.flush()
        await self.repo.seal_transaction(tx)
        return tx, await self.repo.get_entries(tx.id)
