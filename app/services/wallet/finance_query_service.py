"""财务只读查询：峰资金、成员余额、交易流水与总览统计。

与 ``FinanceService``（写路径）分离，避免单文件承担读写两类职责。
所有查询都按 ``finance:read`` 的作用范围过滤，客户端参数不等于授权。
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationException,
    ErrorCode,
    NotFoundException,
)
from app.models.organization import MemberProfile, Peak
from app.models.task import Task
from app.models.user import User
from app.models.wallet import LedgerEntry, LedgerTransaction, WalletAccount
from app.repositories.base import paginate
from app.repositories.organization_repo import OrganizationRepository
from app.repositories.wallet_repo import WalletRepository
from app.services.wallet.finance_scope import (
    ensure_peak_in_scope,
    resolve_allowed_peak_ids,
)


def _peak_display_name(peak: Optional[Peak]) -> Optional[str]:
    if peak is None:
        return None
    return peak.fantasy_name or peak.name


class FinanceQueryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.wallet_repo = WalletRepository(db)
        self.org_repo = OrganizationRepository(db)

    # ------------------------------------------------------------------ 峰

    async def list_peaks(
        self, actor: User, skip: int, limit: int
    ) -> tuple[list[dict], int]:
        allowed = await resolve_allowed_peak_ids(self.db, actor)
        stmt = (
            select(Peak, WalletAccount)
            .outerjoin(
                WalletAccount,
                (WalletAccount.owner_peak_id == Peak.id)
                & (WalletAccount.kind == "peak"),
            )
            .order_by(Peak.id)
        )
        count_stmt = select(func.count()).select_from(Peak)
        if allowed is not None:
            stmt = stmt.where(Peak.id.in_(allowed))
            count_stmt = count_stmt.where(Peak.id.in_(allowed))
        rows = (await self.db.execute(paginate(stmt, skip, limit))).all()
        total = int((await self.db.execute(count_stmt)).scalar_one())

        peak_ids = [peak.id for peak, _ in rows]
        counts: dict[int, int] = {}
        if peak_ids:
            count_rows = await self.db.execute(
                select(MemberProfile.peak_id, func.count())
                .where(MemberProfile.peak_id.in_(peak_ids))
                .group_by(MemberProfile.peak_id)
            )
            counts = {peak_id: int(count) for peak_id, count in count_rows.all()}

        return [
            {
                "peak_id": peak.id,
                "peak_name": _peak_display_name(peak) or peak.name,
                "peak_code": peak.code,
                "account_id": account.id if account else None,
                "balance": int(account.balance) if account else 0,
                "member_count": counts.get(peak.id, 0),
                "is_active": peak.is_active,
            }
            for peak, account in rows
        ], total

    async def get_peak(self, actor: User, peak_id: int) -> dict:
        allowed = await resolve_allowed_peak_ids(self.db, actor)
        ensure_peak_in_scope(peak_id, allowed)
        peak = await self.org_repo.get_peak_by_id(peak_id)
        if peak is None:
            raise NotFoundException(
                message="峰不存在", resource_type="peak", resource_id=peak_id
            )
        account = await self.wallet_repo.get_peak_account(peak_id)
        member_count = await self.org_repo.count_members(peak_id=peak_id)
        return {
            "peak_id": peak.id,
            "peak_name": _peak_display_name(peak) or peak.name,
            "peak_code": peak.code,
            "account_id": account.id if account else None,
            "balance": int(account.balance) if account else 0,
            "member_count": member_count,
            "is_active": peak.is_active,
        }

    async def list_peak_members(
        self, actor: User, peak_id: int, skip: int, limit: int
    ) -> tuple[list[dict], int]:
        allowed = await resolve_allowed_peak_ids(self.db, actor)
        ensure_peak_in_scope(peak_id, allowed)
        peak = await self.org_repo.get_peak_by_id(peak_id)
        if peak is None:
            raise NotFoundException(
                message="峰不存在", resource_type="peak", resource_id=peak_id
            )
        rows = await self.org_repo.list_member_rows(
            peak_id=peak_id, skip=skip, limit=limit
        )
        total = await self.org_repo.count_members(peak_id=peak_id)

        user_ids = [row["user_id"] for row in rows]
        balances: dict[int, tuple[int, int]] = {}
        if user_ids:
            accounts = await self.db.execute(
                select(WalletAccount.id, WalletAccount.owner_user_id, WalletAccount.balance).where(
                    WalletAccount.kind == "user",
                    WalletAccount.owner_user_id.in_(user_ids),
                )
            )
            balances = {
                int(owner_user_id): (int(account_id), int(balance))
                for account_id, owner_user_id, balance in accounts.all()
            }

        items = []
        for row in rows:
            account_id, balance = balances.get(row["user_id"], (None, 0))
            items.append(
                {
                    "member_id": row["id"],
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "display_name": row["display_name"],
                    "student_id": row["student_id"],
                    "membership_status": row["membership_status"],
                    "account_id": account_id,
                    "balance": balance,
                }
            )
        return items, total

    # ------------------------------------------------------------------ 成员

    async def get_user_detail(self, actor: User, user_id: int) -> dict:
        user = (
            await self.db.execute(
                select(User).where(User.id == user_id, User.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if user is None:
            raise NotFoundException(
                message="用户不存在", resource_type="user", resource_id=user_id
            )
        profile = await self.org_repo.get_member_by_user_id(user_id)
        allowed = await resolve_allowed_peak_ids(self.db, actor)
        ensure_peak_in_scope(profile.peak_id if profile else None, allowed)

        peak = None
        if profile is not None and profile.peak_id is not None:
            peak = await self.org_repo.get_peak_by_id(profile.peak_id)
        account = await self.wallet_repo.get_user_account(user_id)
        return {
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name or user.username,
            "member_id": profile.id if profile else None,
            "membership_status": profile.membership_status if profile else None,
            "peak_id": profile.peak_id if profile else None,
            "peak_name": _peak_display_name(peak),
            "account_id": account.id if account else None,
            "balance": int(account.balance) if account else 0,
        }

    # ------------------------------------------------------------------ 流水

    async def list_transactions(
        self,
        actor: User,
        *,
        type_: Optional[str],
        account_id: Optional[int],
        skip: int,
        limit: int,
    ) -> tuple[list[dict], int]:
        allowed = await resolve_allowed_peak_ids(self.db, actor)
        if allowed is not None:
            # 峰范围必须显式指定账户，避免一次拉取全库流水
            if account_id is None:
                raise AuthorizationException(
                    message="峰范围财务查询需指定 account_id",
                    error_code=ErrorCode.Authorization.SCOPE_FORBIDDEN,
                )
            account = await self.wallet_repo.get_account_by_id(account_id)
            if account is None:
                raise NotFoundException(
                    message="资金账户不存在",
                    resource_type="wallet_account",
                    resource_id=account_id,
                )
            ensure_peak_in_scope(account.owner_peak_id, allowed)

        stmt = select(LedgerTransaction).order_by(LedgerTransaction.id.desc())
        if type_:
            stmt = stmt.where(LedgerTransaction.type == type_)
        if account_id is not None:
            stmt = stmt.where(
                LedgerTransaction.id.in_(
                    select(LedgerEntry.transaction_id).where(
                        LedgerEntry.account_id == account_id
                    )
                )
            )
        total = int(
            (await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        txs = list((await self.db.execute(paginate(stmt, skip, limit))).scalars().all())
        return await self._with_entries(txs), total

    async def _with_entries(self, txs: List[LedgerTransaction]) -> list[dict]:
        if not txs:
            return []
        tx_ids = [tx.id for tx in txs]
        entries = list(
            (
                await self.db.execute(
                    select(LedgerEntry)
                    .where(LedgerEntry.transaction_id.in_(tx_ids))
                    .order_by(LedgerEntry.transaction_id, LedgerEntry.entry_no)
                )
            )
            .scalars()
            .all()
        )
        account_ids = {entry.account_id for entry in entries}
        accounts = (
            list(
                (
                    await self.db.execute(
                        select(WalletAccount).where(WalletAccount.id.in_(account_ids))
                    )
                )
                .scalars()
                .all()
            )
            if account_ids
            else []
        )
        account_map = {account.id: account for account in accounts}
        enriched = await self._resolve_entry_owners(accounts)

        actor_ids = {tx.actor_user_id for tx in txs if tx.actor_user_id}
        actor_names: dict[int, str] = {}
        if actor_ids:
            actor_rows = await self.db.execute(
                select(User.id, User.username, User.display_name).where(
                    User.id.in_(actor_ids)
                )
            )
            actor_names = {
                int(uid): (display_name or username)
                for uid, username, display_name in actor_rows.all()
            }

        by_tx: dict[int, list[dict]] = {}
        for entry in entries:
            account = account_map.get(entry.account_id)
            owner = enriched.get(entry.account_id, {})
            by_tx.setdefault(entry.transaction_id, []).append(
                {
                    "account_id": entry.account_id,
                    "kind": account.kind if account else "unknown",
                    "owner_user_id": account.owner_user_id if account else None,
                    "owner_peak_id": account.owner_peak_id if account else None,
                    "owner_task_id": account.owner_task_id if account else None,
                    "owner_name": owner.get("owner_name"),
                    "peak_id": owner.get("peak_id"),
                    "peak_name": owner.get("peak_name"),
                    "delta": int(entry.delta),
                    "balance_after": int(entry.balance_after),
                    "entry_no": entry.entry_no,
                }
            )

        return [
            {
                "transaction_id": tx.id,
                "type": tx.type,
                "business_key": tx.business_key,
                "reason": tx.reason,
                "actor_user_id": tx.actor_user_id,
                "actor_name": actor_names.get(tx.actor_user_id or 0),
                "related_task_id": tx.related_task_id,
                "created_at": tx.created_at,
                "entries": by_tx.get(tx.id, []),
            }
            for tx in txs
        ]

    async def _resolve_entry_owners(
        self, accounts: List[WalletAccount]
    ) -> dict[int, dict]:
        """批量解析分录账户的展示名与所属峰，避免逐个查询。"""
        user_ids = {a.owner_user_id for a in accounts if a.owner_user_id}
        peak_ids = {a.owner_peak_id for a in accounts if a.owner_peak_id}
        task_ids = {a.owner_task_id for a in accounts if a.owner_task_id}

        user_names: dict[int, str] = {}
        user_peak_ids: dict[int, int] = {}
        if user_ids:
            user_rows = await self.db.execute(
                select(User.id, User.username, User.display_name).where(
                    User.id.in_(user_ids)
                )
            )
            user_names = {
                int(uid): (display_name or username)
                for uid, username, display_name in user_rows.all()
            }
            profile_rows = await self.db.execute(
                select(MemberProfile.user_id, MemberProfile.peak_id).where(
                    MemberProfile.user_id.in_(user_ids),
                    MemberProfile.peak_id.is_not(None),
                )
            )
            user_peak_ids = {
                int(uid): int(peak_id) for uid, peak_id in profile_rows.all()
            }

        peak_names: dict[int, str] = {}
        target_peak_ids = set(peak_ids) | set(user_peak_ids.values())
        if target_peak_ids:
            peak_rows = await self.db.execute(
                select(Peak.id, Peak.name, Peak.fantasy_name).where(
                    Peak.id.in_(target_peak_ids)
                )
            )
            peak_names = {
                int(pid): (fantasy_name or name)
                for pid, name, fantasy_name in peak_rows.all()
            }

        task_titles: dict[int, str] = {}
        if task_ids:
            task_rows = await self.db.execute(
                select(Task.id, Task.title).where(Task.id.in_(task_ids))
            )
            task_titles = {int(tid): title for tid, title in task_rows.all()}

        result: dict[int, dict] = {}
        for account in accounts:
            if account.kind == "user":
                peak_id = user_peak_ids.get(account.owner_user_id or 0)
                result[account.id] = {
                    "owner_name": user_names.get(account.owner_user_id or 0),
                    "peak_id": peak_id,
                    "peak_name": peak_names.get(peak_id) if peak_id else None,
                }
            elif account.kind == "peak":
                result[account.id] = {
                    "owner_name": peak_names.get(account.owner_peak_id or 0),
                    "peak_id": account.owner_peak_id,
                    "peak_name": peak_names.get(account.owner_peak_id or 0),
                }
            elif account.kind == "task_escrow":
                result[account.id] = {
                    "owner_name": task_titles.get(account.owner_task_id or 0),
                    "peak_id": None,
                    "peak_name": None,
                }
            else:
                result[account.id] = {
                    "owner_name": None,
                    "peak_id": None,
                    "peak_name": None,
                }
        return result

    # ------------------------------------------------------------------ 统计

    async def stats(self, actor: User) -> dict:
        allowed = await resolve_allowed_peak_ids(self.db, actor)
        if allowed is not None:
            raise AuthorizationException(
                message="峰范围账号请使用峰资金视图",
                error_code=ErrorCode.Authorization.SCOPE_FORBIDDEN,
            )
        rows = await self.db.execute(
            select(WalletAccount.kind, func.coalesce(func.sum(WalletAccount.balance), 0)).group_by(
                WalletAccount.kind
            )
        )
        totals = {kind: int(balance) for kind, balance in rows.all()}
        counts = await self.db.execute(
            select(WalletAccount.kind, func.count()).group_by(WalletAccount.kind)
        )
        account_counts = {kind: int(count) for kind, count in counts.all()}
        return {
            "treasury": totals.get("treasury", 0),
            "peak_total": totals.get("peak", 0),
            "user_total": totals.get("user", 0),
            "task_escrow_total": totals.get("task_escrow", 0),
            "issuance": totals.get("issuance", 0),
            "peak_count": account_counts.get("peak", 0),
            "user_account_count": account_counts.get("user", 0),
        }
