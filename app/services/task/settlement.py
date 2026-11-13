"""任务托管结算：reserve / reward / refund 共用唯一业务键。

- reserve：审核通过时发布者个人账户 → 任务 escrow。
- reward：验收通过时 escrow → 锁定队长，业务键 `task:{id}:settlement`。
- refund：强结/过期/取消时 escrow → 发布者，复用同一 settlement 键互斥。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, ErrorCode
from app.models.task import Task, TaskClaim
from app.repositories.task_repo import TaskRepository
from app.repositories.wallet_repo import WalletRepository
from app.services.wallet.ledger_service import LedgerService


def _settlement_key(task_id: int) -> str:
    return f"task:{task_id}:settlement"


async def reserve_reward(
    db: AsyncSession,
    *,
    task: Task,
    actor_id: int,
    request_id: Optional[str] = None,
) -> None:
    wallet_repo = WalletRepository(db)
    ledger = LedgerService(db)
    publisher_account = await ledger.ensure_user_account(task.publisher_id)
    escrow = await wallet_repo.ensure_task_escrow(task.id)
    await ledger.transfer(
        from_account_id=publisher_account.id,
        to_account_id=escrow.id,
        amount=int(task.reward_total),
        type="task_reserve",
        business_key=f"task:{task.id}:reserve",
        actor_user_id=actor_id,
        related_task_id=task.id,
        request_id=request_id,
        source_type="task",
        source_id=str(task.id),
    )


async def settle_reward(
    db: AsyncSession,
    *,
    task: Task,
    claim: TaskClaim,
    actor_id: int,
    request_id: Optional[str] = None,
) -> None:
    repo = TaskRepository(db)
    if await repo.get_settlement_transaction(task.id) is not None:
        raise ConflictException(
            message="该任务已结算，不能重复发放或退款",
            error_code=ErrorCode.Conflict.TASK_ALREADY_SETTLED,
        )
    wallet_repo = WalletRepository(db)
    ledger = LedgerService(db)
    escrow = await wallet_repo.ensure_task_escrow(task.id)
    leader_account = await ledger.ensure_user_account(claim.leader_user_id)
    await ledger.transfer(
        from_account_id=escrow.id,
        to_account_id=leader_account.id,
        amount=int(task.reward_total),
        type="task_reward",
        business_key=_settlement_key(task.id),
        actor_user_id=actor_id,
        related_task_id=task.id,
        request_id=request_id,
        source_type="task",
        source_id=str(task.id),
    )


async def refund_reward(
    db: AsyncSession,
    *,
    task: Task,
    actor_id: int,
    reason: str,
    request_id: Optional[str] = None,
) -> None:
    repo = TaskRepository(db)
    if await repo.get_settlement_transaction(task.id) is not None:
        raise ConflictException(
            message="该任务已结算，不能重复发放或退款",
            error_code=ErrorCode.Conflict.TASK_ALREADY_SETTLED,
        )
    wallet_repo = WalletRepository(db)
    ledger = LedgerService(db)
    escrow = await wallet_repo.ensure_task_escrow(task.id)
    publisher_account = await ledger.ensure_user_account(task.publisher_id)
    await ledger.transfer(
        from_account_id=escrow.id,
        to_account_id=publisher_account.id,
        amount=int(task.reward_total),
        type="task_refund",
        business_key=_settlement_key(task.id),
        actor_user_id=actor_id,
        related_task_id=task.id,
        reason=reason,
        request_id=request_id,
        source_type="task",
        source_id=str(task.id),
    )
