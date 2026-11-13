"""管理员财务 API：账户/总库、调账、调拨与对账。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import get_client_meta
from app.database import get_db
from app.dependencies_services import get_audit_service
from app.middleware.rbac import require_admin_2fa, require_permission
from app.models.user import User
from app.repositories.wallet_repo import WalletRepository
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.wallet import (
    FinanceAccountOut,
    FinanceAdjustCreate,
    FinanceAllocationCreate,
    FinanceMemberRowOut,
    FinancePeakRowOut,
    FinancePeakTransferCreate,
    FinanceReversalCreate,
    FinanceReversalOut,
    FinanceStatsOut,
    FinanceTransactionOut,
    FinanceTransactionRowOut,
    FinanceUserDetailOut,
    ReconciliationOut,
)
from app.services.audit_service import AuditService
from app.services.wallet.finance_query_service import FinanceQueryService
from app.services.wallet.finance_service import FinanceService

router = APIRouter(dependencies=[Depends(require_admin_2fa())])


def get_finance_service(db: AsyncSession = Depends(get_db)) -> FinanceService:
    return FinanceService(db)


def get_finance_query_service(
    db: AsyncSession = Depends(get_db),
) -> FinanceQueryService:
    return FinanceQueryService(db)


@router.get("/accounts", response_model=PaginatedResponse[FinanceAccountOut])
async def list_accounts(
    pagination: PaginationParams = Depends(),
    kind: Optional[str] = None,
    service: FinanceService = Depends(get_finance_service),
    current_user: User = Depends(require_permission("finance", "read")),
) -> Any:
    items = await service.list_accounts(kind, pagination.skip, pagination.limit)
    total = await service.count_accounts(kind)
    return PaginatedResponse(
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.get("/treasury", response_model=FinanceAccountOut)
async def get_treasury(
    service: FinanceService = Depends(get_finance_service),
    current_user: User = Depends(require_permission("finance", "read")),
) -> Any:
    return await service.get_treasury()


@router.post("/adjustments", response_model=FinanceTransactionOut)
async def create_adjustment(
    body: FinanceAdjustCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: FinanceService = Depends(get_finance_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("finance", "adjust")),
) -> Any:
    result = await service.adjust(
        actor_id=current_user.id,
        target_account_id=body.target_account_id,
        direction=body.direction,
        amount=int(body.amount),
        reason=body.reason,
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    replayed = bool(result.pop("_replayed", False))
    if not replayed:
        await audit.record_atomic(
            action="finance.adjust",
            resource_type="wallet_account",
            resource_id=str(body.target_account_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={
                "direction": body.direction,
                "amount": body.amount,
                "reason": body.reason,
            },
            **get_client_meta(request),
        )
    return result


@router.post("/allocations", response_model=FinanceTransactionOut)
async def create_allocation(
    body: FinanceAllocationCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: FinanceService = Depends(get_finance_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("finance", "allocate")),
) -> Any:
    result = await service.allocate(
        actor_id=current_user.id,
        from_account_id=body.from_account_id,
        to_account_id=body.to_account_id,
        amount=int(body.amount),
        reason=body.reason,
        operation_kind=body.operation_kind,
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    replayed = bool(result.pop("_replayed", False))
    if not replayed:
        await audit.record_atomic(
            action="finance.allocate",
            resource_type="wallet_account",
            resource_id=str(body.to_account_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={
                "from_account_id": body.from_account_id,
                "to_account_id": body.to_account_id,
                "amount": body.amount,
                "reason": body.reason,
            },
            **get_client_meta(request),
        )
    return result


@router.post("/reconciliations", response_model=ReconciliationOut)
async def run_reconciliation(
    request: Request,
    service: FinanceService = Depends(get_finance_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("finance", "reconcile")),
) -> Any:
    result = await service.reconcile(triggered_by=current_user.id, commit=False)
    await audit.record_atomic(
        action="finance.reconcile",
        resource_type="reconciliation",
        resource_id=str(result["id"]),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"status": result["status"], "counts": result["counts"]},
        **get_client_meta(request),
    )
    return result


@router.get("/reconciliations", response_model=PaginatedResponse[ReconciliationOut])
async def list_reconciliations(
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("finance", "reconcile")),
) -> Any:
    repo = WalletRepository(db)
    items = await repo.list_reconciliation_runs(pagination.skip, pagination.limit)
    total = await repo.count_reconciliation_runs()
    return PaginatedResponse(
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


# ---------------------------------------------------------------- 读模型（finance:read + 范围）


@router.get("/stats", response_model=FinanceStatsOut)
async def get_stats(
    service: FinanceQueryService = Depends(get_finance_query_service),
    current_user: User = Depends(require_permission("finance", "read")),
) -> Any:
    """全范围财务总览；峰范围账号请使用峰资金视图。"""
    return await service.stats(current_user)


@router.get("/peaks", response_model=PaginatedResponse[FinancePeakRowOut])
async def list_finance_peaks(
    pagination: PaginationParams = Depends(),
    service: FinanceQueryService = Depends(get_finance_query_service),
    current_user: User = Depends(require_permission("finance", "read")),
) -> Any:
    """峰资金列表：峰身份 + 峰账户余额 + 在册成员数，按授权范围过滤。"""
    items, total = await service.list_peaks(
        current_user, pagination.skip, pagination.limit
    )
    return PaginatedResponse(
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.get("/peaks/{peak_id}", response_model=FinancePeakRowOut)
async def get_finance_peak(
    peak_id: int,
    service: FinanceQueryService = Depends(get_finance_query_service),
    current_user: User = Depends(require_permission("finance", "read")),
) -> Any:
    """单个峰资金视图（峰范围账号仅能读绑定峰）。"""
    return await service.get_peak(current_user, peak_id)


@router.get(
    "/peaks/{peak_id}/members", response_model=PaginatedResponse[FinanceMemberRowOut]
)
async def list_finance_peak_members(
    peak_id: int,
    pagination: PaginationParams = Depends(),
    service: FinanceQueryService = Depends(get_finance_query_service),
    current_user: User = Depends(require_permission("finance", "read")),
) -> Any:
    """峰成员资金摘要：仅身份与余额，最小披露。"""
    items, total = await service.list_peak_members(
        current_user, peak_id, pagination.skip, pagination.limit
    )
    return PaginatedResponse(
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.get("/users/{user_id}", response_model=FinanceUserDetailOut)
async def get_finance_user(
    user_id: int,
    service: FinanceQueryService = Depends(get_finance_query_service),
    current_user: User = Depends(require_permission("finance", "read")),
) -> Any:
    """成员资金详情：账号、成员档案与钱包余额。"""
    return await service.get_user_detail(current_user, user_id)


@router.get("/transactions", response_model=PaginatedResponse[FinanceTransactionRowOut])
async def list_transactions(
    pagination: PaginationParams = Depends(),
    type_: Optional[str] = Query(None, alias="type"),
    account_id: Optional[int] = Query(None, gt=0),
    service: FinanceQueryService = Depends(get_finance_query_service),
    current_user: User = Depends(require_permission("finance", "read")),
) -> Any:
    """交易/分录查询：统一账本，不另建调整日志账本。"""
    items, total = await service.list_transactions(
        current_user,
        type_=type_,
        account_id=account_id,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return PaginatedResponse(
        items=items, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.post("/peak-transfers", response_model=FinanceTransactionOut)
async def create_peak_transfer(
    body: FinancePeakTransferCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: FinanceService = Depends(get_finance_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("finance", "transfer")),
) -> Any:
    """峰间调拨：两侧峰均需在授权范围内，锁账户后整笔成功或失败。"""
    result = await service.peak_transfer(
        actor_id=current_user.id,
        from_peak_id=body.from_peak_id,
        to_peak_id=body.to_peak_id,
        amount=int(body.amount),
        reason=body.reason,
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    replayed = bool(result.pop("_replayed", False))
    if not replayed:
        await audit.record_atomic(
            action="finance.peak_transfer",
            resource_type="wallet_account",
            resource_id=str(body.from_peak_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={
                "from_peak_id": body.from_peak_id,
                "to_peak_id": body.to_peak_id,
                "amount": body.amount,
                "reason": body.reason,
            },
            **get_client_meta(request),
        )
    return result


@router.post("/reversals", response_model=FinanceReversalOut)
async def create_reversal(
    body: FinanceReversalCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    service: FinanceService = Depends(get_finance_service),
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("finance", "adjust")),
) -> Any:
    """交易冲正：保留原流水，按相反分录取反；一笔原交易只允许冲正一次。"""
    result = await service.reverse(
        actor_id=current_user.id,
        transaction_id=body.transaction_id,
        reason=body.reason,
        idempotency_key=idempotency_key,
        request_id=get_client_meta(request).get("request_id"),
    )
    replayed = bool(result.pop("_replayed", False))
    if not replayed:
        await audit.record_atomic(
            action="finance.reversal",
            resource_type="ledger_transaction",
            resource_id=str(body.transaction_id),
            actor_id=current_user.id,
            actor_username=current_user.username,
            detail={
                "reversal_transaction_id": result["transaction_id"],
                "reason": body.reason,
            },
            **get_client_meta(request),
        )
    return result
