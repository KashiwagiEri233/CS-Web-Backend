"""财务服务：总库/峰/成员资金调拨、发行回收与对账。"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ErrorCode,
    NotFoundException,
    ValidationException,
)
from app.core.timezone import now_utc
from app.models.user import User
from app.models.wallet import (
    ACCOUNT_KIND_ISSUANCE,
    ACCOUNT_KIND_TREASURY,
    LedgerEntry,
    ReconciliationRun,
    WalletAccount,
)
from app.repositories.organization_repo import OrganizationRepository
from app.repositories.wallet_repo import WalletRepository
from app.services.wallet.finance_scope import (
    ensure_peak_in_scope,
    resolve_allowed_peak_ids,
)
from app.services.wallet.ledger_service import LedgerService
from app.services.wallet.transfer_service import canonical_request_hash


class FinanceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = WalletRepository(db)
        self.org_repo = OrganizationRepository(db)
        self.ledger = LedgerService(db)

    # ------------------------------------------------------------------ 作用范围

    async def _allowed_peak_ids(self, actor_id: int) -> Optional[set[int]]:
        """按操作人绑定解析可写峰范围；None 表示全范围。"""
        actor = (
            await self.db.execute(select(User).where(User.id == actor_id))
        ).scalar_one_or_none()
        if actor is None:
            raise NotFoundException(
                message="操作人不存在", resource_type="user", resource_id=actor_id
            )
        return await resolve_allowed_peak_ids(self.db, actor)

    async def _ensure_account_in_scope(
        self, account: WalletAccount, allowed: Optional[set[int]]
    ) -> None:
        """峰范围账号只能操作绑定峰及其成员的资金。"""
        if allowed is None:
            return
        if account.kind == "peak":
            ensure_peak_in_scope(account.owner_peak_id, allowed)
            return
        if account.kind == "user":
            profile = await self.org_repo.get_member_by_user_id(
                account.owner_user_id or 0
            )
            ensure_peak_in_scope(profile.peak_id if profile else None, allowed)
            return
        raise AuthorizationException(
            message="该账户不在授权范围内",
            error_code=ErrorCode.Authorization.SCOPE_FORBIDDEN,
            details={"kind": account.kind},
        )

    async def get_treasury(self) -> WalletAccount:
        treasury, _ = await self.ledger.ensure_system_accounts()
        return treasury

    async def list_accounts(self, kind: Optional[str], skip: int, limit: int) -> list:
        stmt = select(WalletAccount).order_by(WalletAccount.id)
        if kind:
            stmt = stmt.where(WalletAccount.kind == kind)
        result = await self.db.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_accounts(self, kind: Optional[str]) -> int:
        stmt = select(func.count()).select_from(WalletAccount)
        if kind:
            stmt = stmt.where(WalletAccount.kind == kind)
        return int((await self.db.execute(stmt)).scalar_one())

    async def _idempotent_replay(
        self, actor_id: int, operation: str, key: Optional[str], request_hash: str
    ) -> Optional[dict]:
        if not key:
            raise ValidationException(
                message="缺少 Idempotency-Key", details={"header": "Idempotency-Key"}
            )
        existing = await self.repo.get_idempotency_record(actor_id, operation, key)
        if existing is None:
            return None
        if existing.canonical_request_hash != request_hash:
            raise ConflictException(
                message="相同 Idempotency-Key 的请求内容不一致",
                error_code=ErrorCode.Conflict.IDEMPOTENCY_KEY_REUSED,
            )
        return {**dict(existing.response_body or {}), "_replayed": True}

    async def _store_idempotency(
        self,
        actor_id: int,
        operation: str,
        key: str,
        request_hash: str,
        response: dict,
    ) -> None:
        await self.repo.create_idempotency_record(
            {
                "actor_id": actor_id,
                "operation": operation,
                "key": key,
                "canonical_request_hash": request_hash,
                "status_code": 200,
                "response_body": response,
                "expires_at": now_utc()
                + timedelta(seconds=settings.IDEMPOTENCY_RECORD_TTL_SECONDS),
            }
        )

    async def adjust(
        self,
        *,
        actor_id: int,
        target_account_id: int,
        direction: str,
        amount: int,
        reason: str,
        idempotency_key: Optional[str],
        request_id: Optional[str],
    ) -> dict:
        if direction not in ("issue", "burn"):
            raise ValidationException(message="direction 必须为 issue 或 burn")
        if amount <= 0:
            raise ValidationException(
                message="金额必须为正整数",
                error_code=ErrorCode.Validation.INVALID_MONEY_AMOUNT,
            )
        _, issuance = await self.ledger.ensure_system_accounts()
        target = await self.repo.get_account_by_id(target_account_id)
        if target is None:
            raise NotFoundException(
                message="目标账户不存在",
                resource_type="wallet_account",
                resource_id=target_account_id,
            )
        if target.kind == ACCOUNT_KIND_ISSUANCE:
            raise ValidationException(message="不能对发行账户直接调账")
        await self._ensure_account_in_scope(
            target, await self._allowed_peak_ids(actor_id)
        )

        request_hash = canonical_request_hash(
            {
                "actor_id": actor_id,
                "operation": "adjust",
                "target": target_account_id,
                "direction": direction,
                "amount": amount,
                "reason": reason,
            }
        )
        replay = await self._idempotent_replay(
            actor_id, "finance_adjust", idempotency_key, request_hash
        )
        if replay is not None:
            return replay

        if direction == "issue":
            tx, _ = await self.ledger.transfer(
                from_account_id=issuance.id,
                to_account_id=target.id,
                amount=amount,
                type="issue",
                business_key=f"adjustment:{idempotency_key}",
                actor_user_id=actor_id,
                reason=reason,
                request_id=request_id,
                source_type="finance_adjust",
                source_id=idempotency_key,
            )
        else:
            tx, _ = await self.ledger.transfer(
                from_account_id=target.id,
                to_account_id=issuance.id,
                amount=amount,
                type="burn",
                business_key=f"adjustment:{idempotency_key}",
                actor_user_id=actor_id,
                reason=reason,
                request_id=request_id,
                source_type="finance_adjust",
                source_id=idempotency_key,
            )
        response = {
            "transaction_id": tx.id,
            "business_key": tx.business_key,
            "amount": str(amount),
            "direction": direction,
            "target_account_id": target.id,
            "_replayed": False,
        }
        await self._store_idempotency(
            actor_id, "finance_adjust", idempotency_key or "", request_hash, response
        )
        return response

    async def allocate(
        self,
        *,
        actor_id: int,
        from_account_id: int,
        to_account_id: int,
        amount: int,
        reason: str,
        operation_kind: str,
        idempotency_key: Optional[str],
        request_id: Optional[str],
    ) -> dict:
        """总库↔峰、峰↔总库、峰→成员 白名单调拨。"""
        if amount <= 0:
            raise ValidationException(
                message="金额必须为正整数",
                error_code=ErrorCode.Validation.INVALID_MONEY_AMOUNT,
            )
        accounts = await self.repo.lock_accounts([from_account_id, to_account_id])
        by_id = {a.id: a for a in accounts}
        src = by_id.get(from_account_id)
        dst = by_id.get(to_account_id)
        if src is None or dst is None:
            raise NotFoundException(message="资金账户不存在")

        # 操作类型与账户路径一一对应，避免用 allocation 名义做峰间调拨
        kind_paths = {
            "allocation": ("treasury", "peak"),
            "return": ("peak", "treasury"),
            "member_allocation": ("peak", "user"),
            "peak_transfer": ("peak", "peak"),
        }
        if kind_paths.get(operation_kind) != (src.kind, dst.kind):
            raise ValidationException(
                message="调拨类型与账户路径不匹配",
                error_code=ErrorCode.Authorization.SCOPE_FORBIDDEN,
                details={
                    "operation_kind": operation_kind,
                    "from_kind": src.kind,
                    "to_kind": dst.kind,
                },
            )

        allowed_peak_ids = await self._allowed_peak_ids(actor_id)
        await self._ensure_account_in_scope(src, allowed_peak_ids)
        await self._ensure_account_in_scope(dst, allowed_peak_ids)

        request_hash = canonical_request_hash(
            {
                "actor_id": actor_id,
                "operation": "allocate",
                "from": from_account_id,
                "to": to_account_id,
                "amount": amount,
                "reason": reason,
                "kind": operation_kind,
            }
        )
        replay = await self._idempotent_replay(
            actor_id, "finance_allocate", idempotency_key, request_hash
        )
        if replay is not None:
            return replay

        transfer_types = {
            "allocation": "allocate_peak",
            "return": "return_peak",
            "member_allocation": "allocate_member",
            "peak_transfer": "peak_transfer",
        }
        transfer_type = transfer_types[operation_kind]
        tx, _ = await self.ledger.transfer(
            from_account_id=src.id,
            to_account_id=dst.id,
            amount=amount,
            type=transfer_type,
            business_key=f"{operation_kind}:{idempotency_key}",
            actor_user_id=actor_id,
            reason=reason,
            request_id=request_id,
            source_type="finance_allocate",
            source_id=idempotency_key,
        )
        response = {
            "transaction_id": tx.id,
            "business_key": tx.business_key,
            "amount": str(amount),
            "from_account_id": src.id,
            "to_account_id": dst.id,
            "_replayed": False,
        }
        await self._store_idempotency(
            actor_id, "finance_allocate", idempotency_key or "", request_hash, response
        )
        return response

    async def peak_transfer(
        self,
        *,
        actor_id: int,
        from_peak_id: int,
        to_peak_id: int,
        amount: int,
        reason: str,
        idempotency_key: Optional[str],
        request_id: Optional[str],
    ) -> dict:
        """峰间调拨：两侧峰账户加锁后复用调拨白名单。"""
        if from_peak_id == to_peak_id:
            raise ValidationException(message="源峰与目标峰不能相同")
        src = await self.repo.get_peak_account(from_peak_id)
        dst = await self.repo.get_peak_account(to_peak_id)
        if src is None or dst is None:
            raise NotFoundException(
                message="峰资金账户不存在",
                details={"from_peak_id": from_peak_id, "to_peak_id": to_peak_id},
            )
        return await self.allocate(
            actor_id=actor_id,
            from_account_id=src.id,
            to_account_id=dst.id,
            amount=amount,
            reason=reason,
            operation_kind="peak_transfer",
            idempotency_key=idempotency_key,
            request_id=request_id,
        )

    async def reverse(
        self,
        *,
        actor_id: int,
        transaction_id: int,
        reason: str,
        idempotency_key: Optional[str],
        request_id: Optional[str],
    ) -> dict:
        """冲正一笔交易：保留原流水，按相反分录取反，金额与账户范围同样校验。"""
        original = await self.repo.get_transaction(transaction_id)
        if original is None:
            raise NotFoundException(
                message="原交易不存在",
                resource_type="ledger_transaction",
                resource_id=transaction_id,
            )
        entries = await self.repo.get_entries(transaction_id)
        allowed = await self._allowed_peak_ids(actor_id)
        for entry in entries:
            account = await self.repo.get_account_by_id(entry.account_id)
            if account is None:
                raise ConflictException(message="原交易分录账户不存在")
            await self._ensure_account_in_scope(account, allowed)

        request_hash = canonical_request_hash(
            {
                "actor_id": actor_id,
                "operation": "reverse",
                "transaction_id": transaction_id,
                "reason": reason,
            }
        )
        replay = await self._idempotent_replay(
            actor_id, "finance_reversal", idempotency_key, request_hash
        )
        if replay is not None:
            return replay

        tx, reversed_entries = await self.ledger.reverse(
            original_transaction_id=transaction_id,
            actor_user_id=actor_id,
            reason=reason,
            business_key=f"reversal:{original.business_key}",
            request_id=request_id,
        )
        amount = sum(int(entry.delta) for entry in reversed_entries if int(entry.delta) > 0)
        response = {
            "transaction_id": tx.id,
            "business_key": tx.business_key,
            "amount": amount,
            "original_transaction_id": original.id,
        }
        await self._store_idempotency(
            actor_id, "finance_reversal", idempotency_key or "", request_hash, response
        )
        return response

    async def reconcile(
        self, *, triggered_by: int, commit: bool = True
    ) -> dict:
        """执行一次对账，报告异常计数；不改余额。"""
        run = ReconciliationRun(
            started_at=now_utc(), status="running", triggered_by=triggered_by
        )
        self.db.add(run)
        await self.db.flush()

        counts: dict = {}
        counts["unbalanced_transactions"] = int(
            (
                await self.db.execute(
                    text(
                        """
                        SELECT count(*) FROM (
                          SELECT transaction_id
                          FROM ledger_entries
                          GROUP BY transaction_id
                          HAVING COALESCE(sum(delta), 0) <> 0 OR count(*) < 2
                        ) t
                        """
                    )
                )
            ).scalar_one()
        )
        counts["negative_accounts"] = int(
            (
                await self.db.execute(
                    text(
                        "SELECT count(*) FROM wallet_accounts "
                        "WHERE kind <> 'issuance' AND balance < 0"
                    )
                )
            ).scalar_one()
        )
        counts["projection_mismatches"] = int(
            (
                await self.db.execute(
                    text(
                        """
                        SELECT count(*) FROM (
                          SELECT a.id
                          FROM wallet_accounts a
                          LEFT JOIN ledger_entries e ON e.account_id = a.id
                          GROUP BY a.id, a.balance
                          HAVING a.balance <> COALESCE(sum(e.delta), 0)
                        ) t
                        """
                    )
                )
            ).scalar_one()
        )
        total_balance = int(
            (
                await self.db.execute(
                    text(
                        "SELECT COALESCE(sum(balance), 0) FROM wallet_accounts "
                        "WHERE kind <> 'issuance'"
                    )
                )
            ).scalar_one()
        )
        issuance_balance = int(
            (
                await self.db.execute(
                    text(
                        "SELECT COALESCE(sum(balance), 0) FROM wallet_accounts "
                        "WHERE kind = 'issuance'"
                    )
                )
            ).scalar_one()
        )
        counts["circulation_difference"] = total_balance + issuance_balance

        run.status = "ok" if all(v == 0 for v in counts.values()) else "failed"
        run.finished_at = now_utc()
        run.counts = counts
        run.differences = {}
        await self.db.flush()
        if commit:
            await self.db.commit()
        return {
            "id": run.id,
            "status": run.status,
            "counts": counts,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }
