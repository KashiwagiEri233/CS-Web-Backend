"""本人钱包 API：余额、流水、收款人搜索、转账与交易详情。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationException, NotFoundException
from app.core.request_context import get_client_meta
from app.database import get_db
from app.dependencies import get_current_active_user
from app.dependencies_services import get_audit_service, get_rbac_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.repositories.wallet_repo import WalletRepository
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.wallet import (
    LedgerEntryOut,
    LedgerTransactionOut,
    RecipientOut,
    TransferCreate,
    TransferOut,
    WalletLeaderboardEntryOut,
    WalletProfileOut,
    WalletSummaryOut,
)
from app.services.audit_service import AuditService
from app.services.levels import calculate_level
from app.services.rbac.rbac_service import RBACService
from app.services.wallet.ledger_service import LedgerService
from app.services.wallet.transfer_service import WalletTransferService

router = APIRouter()


def get_ledger_service(db: AsyncSession = Depends(get_db)) -> LedgerService:
    return LedgerService(db)


def get_transfer_service(db: AsyncSession = Depends(get_db)) -> WalletTransferService:
    return WalletTransferService(db)


@router.get("/me", response_model=WalletSummaryOut)
async def get_my_wallet(
    ledger: LedgerService = Depends(get_ledger_service),
    current_user: User = Depends(require_permission("wallet", "read")),
) -> Any:
    """本人钱包余额与托管汇总（金额字符串）。"""
    return await ledger.get_summary(current_user.id)


@router.get("/me/profile", response_model=WalletProfileOut)
async def get_my_profile(
    ledger: LedgerService = Depends(get_ledger_service),
    current_user: User = Depends(require_permission("wallet", "read")),
) -> Any:
    """统一余额档案：可用余额、托管汇总与按余额派生的等级。"""
    summary = await ledger.get_summary(current_user.id)
    level = calculate_level(summary["balance"])
    return {**summary, "level": level["level"], "level_title": level["title"]}


@router.get("/leaderboard", response_model=list[WalletLeaderboardEntryOut])
async def wallet_leaderboard(
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("wallet", "read")),
) -> Any:
    """公开余额排行：仅包含已同意公开的有效用户。"""
    rows = await WalletRepository(db).leaderboard(limit)
    items = []
    for user, account in rows:
        level = calculate_level(int(account.balance))
        items.append(
            {
                "user_id": user.id,
                "display_name": user.display_name or user.username,
                "balance": int(account.balance),
                "level": level["level"],
                "level_title": level["title"],
            }
        )
    return items


@router.get("/me/entries", response_model=PaginatedResponse[LedgerEntryOut])
async def list_my_entries(
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("wallet", "read")),
) -> Any:
    """本人钱包流水（最多 100 条/页，稳定倒序）。"""
    repo = WalletRepository(db)
    account = await repo.ensure_user_account(current_user.id)
    limit = min(pagination.limit, 100)
    entries = await repo.list_account_entries(account.id, pagination.skip, limit)
    total = await repo.count_account_entries(account.id)
    return PaginatedResponse(
        items=entries, total=total, skip=pagination.skip, limit=limit
    )


@router.get("/recipients", response_model=list[RecipientOut])
async def search_recipients(
    q: str = Query(min_length=3, max_length=50),
    transfer: WalletTransferService = Depends(get_transfer_service),
    current_user: User = Depends(require_permission("wallet", "transfer")),
) -> Any:
    """按用户名/展示名前缀搜索收款人（最小披露）。"""
    return await transfer.list_recipients(q)


@router.post("/transfers", response_model=TransferOut)
async def create_transfer(
    body: TransferCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    transfer: WalletTransferService = Depends(get_transfer_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("wallet", "transfer")),
) -> Any:
    """本人钱包转账：仅从登录用户钱包扣款，同事务写账本 + 幂等 + 审计。"""
    result = await transfer.transfer(
        actor=current_user,
        recipient_user_id=body.recipient_user_id,
        amount_text=body.amount,
        remark=body.remark,
        related_task_id=body.related_task_id,
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    replayed = bool(result.pop("_replayed", False))
    if not replayed:
        # record_atomic 在同一请求会话提交账本、幂等与审计
        await audit.record_atomic(
            action="wallet.transfer",
            resource_type="wallet_transfer",
            resource_id=str(result.get("transaction_id")),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={
                "recipient_user_id": body.recipient_user_id,
                "amount": str(body.amount),
                "related_task_id": body.related_task_id,
            },
            **get_client_meta(request),
        )
    return result


@router.get("/transfers/{transaction_id}", response_model=LedgerTransactionOut)
async def get_transfer_detail(
    transaction_id: int,
    db: AsyncSession = Depends(get_db),
    rbac_service: RBACService = Depends(get_rbac_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """交易详情：仅参与方、超级用户或具备 finance:read 的财务角色可读。"""
    repo = WalletRepository(db)
    tx = await repo.get_transaction(transaction_id)
    if tx is None:
        raise NotFoundException(
            message="交易不存在",
            resource_type="ledger_transaction",
            resource_id=transaction_id,
        )
    entries = await repo.get_entries(transaction_id)

    allowed = current_user.is_superuser
    if not allowed:
        account = await repo.get_user_account(current_user.id)
        allowed = account is not None and any(
            entry.account_id == account.id for entry in entries
        )
    if not allowed:
        permissions = await rbac_service.get_user_permissions(
            current_user.id, getattr(current_user, "authorization_version", None)
        )
        allowed = "finance:read" in permissions
    if not allowed:
        raise AuthorizationException(
            message="无权查看该交易",
        )

    return {
        "id": tx.id,
        "type": tx.type,
        "business_key": tx.business_key,
        "reason": tx.reason,
        "related_task_id": tx.related_task_id,
        "created_at": tx.created_at,
        "entries": entries,
    }
