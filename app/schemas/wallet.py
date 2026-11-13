"""钱包与账本 API schema：金额跨 JSON 边界一律十进制字符串。"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.schemas.base import TZModel


class WalletAccountOut(TZModel):
    id: int
    kind: str
    owner_user_id: Optional[int] = None
    owner_peak_id: Optional[int] = None
    owner_task_id: Optional[int] = None
    balance: int
    is_active: bool = True

    @field_serializer("balance")
    def _balance_str(self, value: int) -> str:
        return str(value)


class WalletSummaryOut(TZModel):
    """本人钱包摘要：可用余额 + 托管汇总。"""

    user_id: int
    balance: int
    escrow_total: int
    account_id: Optional[int] = None

    @field_serializer("balance", "escrow_total")
    def _money_str(self, value: int) -> str:
        return str(value)


class LedgerEntryOut(TZModel):
    id: int
    transaction_id: int
    account_id: int
    delta: int
    balance_after: int
    entry_no: int
    created_at: Optional[datetime] = None

    @field_serializer("delta", "balance_after")
    def _money_str(self, value: int) -> str:
        return str(value)


class LedgerTransactionOut(TZModel):
    id: int
    type: str
    business_key: str
    reason: Optional[str] = None
    related_task_id: Optional[int] = None
    created_at: Optional[datetime] = None
    entries: List[LedgerEntryOut] = Field(default_factory=list)


class TransferCreate(BaseModel):
    """本人钱包转账：付款人由登录身份决定，禁止客户端传入。"""

    recipient_user_id: int = Field(gt=0)
    amount: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    remark: Optional[str] = Field(None, max_length=200)
    related_task_id: Optional[int] = Field(None, gt=0)

    model_config = ConfigDict(extra="forbid")


class TransferOut(TZModel):
    transaction_id: int
    business_key: str
    from_account_id: int
    to_account_id: int
    amount: int
    created_at: Optional[datetime] = None

    @field_serializer("amount")
    def _money_str(self, value: int) -> str:
        return str(value)


class RecipientOut(BaseModel):
    """收款人候选：最小披露资料。"""

    user_id: int
    display_name: Optional[str] = None
    username: Optional[str] = None


class WalletProfileOut(TZModel):
    """统一余额档案：等级由当前可用余额派生。"""

    user_id: int
    balance: int
    escrow_total: int
    level: int
    level_title: str

    @field_serializer("balance", "escrow_total")
    def _money_str(self, value: int) -> str:
        return str(value)


class WalletLeaderboardEntryOut(TZModel):
    """公开余额排行条目：仅包含已同意公开的有效用户。"""

    user_id: int
    display_name: Optional[str] = None
    balance: int
    level: int
    level_title: str

    @field_serializer("balance")
    def _money_str(self, value: int) -> str:
        return str(value)


class FinanceAccountOut(TZModel):
    id: int
    kind: str
    owner_user_id: Optional[int] = None
    owner_peak_id: Optional[int] = None
    owner_task_id: Optional[int] = None
    balance: int
    is_active: bool = True

    @field_serializer("balance")
    def _balance_str(self, value: int) -> str:
        return str(value)


class FinanceAdjustCreate(BaseModel):
    target_account_id: int = Field(gt=0)
    direction: str = Field(pattern=r"^(issue|burn)$")
    amount: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    reason: str = Field(min_length=1, max_length=200)

    model_config = ConfigDict(extra="forbid")


class FinanceAllocationCreate(BaseModel):
    from_account_id: int = Field(gt=0)
    to_account_id: int = Field(gt=0)
    amount: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    reason: str = Field(min_length=1, max_length=200)
    operation_kind: str = Field(
        default="allocation", pattern=r"^(allocation|return|member_allocation)$"
    )

    model_config = ConfigDict(extra="forbid")


class FinanceTransactionOut(TZModel):
    transaction_id: int
    business_key: str
    amount: int
    direction: Optional[str] = None
    target_account_id: Optional[int] = None
    from_account_id: Optional[int] = None
    to_account_id: Optional[int] = None

    @field_serializer("amount")
    def _money_str(self, value: int) -> str:
        return str(value)


class ReconciliationOut(TZModel):
    id: int
    status: str
    counts: dict = Field(default_factory=dict)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


# ---------------------------------------------------------------- 财务读模型


class FinanceEntryOut(TZModel):
    """交易分录视图：账户归属与展示名在同一行返回，避免前端拼全库。"""

    account_id: int
    kind: str
    owner_user_id: Optional[int] = None
    owner_peak_id: Optional[int] = None
    owner_task_id: Optional[int] = None
    owner_name: Optional[str] = None
    # 个人账户所属峰（成员档案），峰账户即自身
    peak_id: Optional[int] = None
    peak_name: Optional[str] = None
    delta: int
    balance_after: int
    entry_no: int

    @field_serializer("delta", "balance_after")
    def _money_str(self, value: int) -> str:
        return str(value)


class FinanceTransactionRowOut(TZModel):
    """财务流水行：交易头 + 分录。"""

    transaction_id: int
    type: str
    business_key: str
    reason: Optional[str] = None
    actor_user_id: Optional[int] = None
    actor_name: Optional[str] = None
    related_task_id: Optional[int] = None
    created_at: Optional[datetime] = None
    entries: List[FinanceEntryOut] = Field(default_factory=list)


class FinancePeakRowOut(TZModel):
    """峰资金视图：峰身份 + 峰账户余额 + 在册成员数。"""

    peak_id: int
    peak_name: str
    peak_code: str
    account_id: Optional[int] = None
    balance: int
    member_count: int
    is_active: bool = True

    @field_serializer("balance")
    def _money_str(self, value: int) -> str:
        return str(value)


class FinanceMemberRowOut(TZModel):
    """峰成员资金视图：最小披露，仅身份与余额。"""

    member_id: int
    user_id: int
    username: str
    display_name: Optional[str] = None
    student_id: Optional[str] = None
    membership_status: str
    account_id: Optional[int] = None
    balance: int

    @field_serializer("balance")
    def _money_str(self, value: int) -> str:
        return str(value)


class FinanceUserDetailOut(TZModel):
    """成员资金详情：账号、成员档案与钱包余额。"""

    user_id: int
    username: str
    display_name: Optional[str] = None
    member_id: Optional[int] = None
    membership_status: Optional[str] = None
    peak_id: Optional[int] = None
    peak_name: Optional[str] = None
    account_id: Optional[int] = None
    balance: int

    @field_serializer("balance")
    def _money_str(self, value: int) -> str:
        return str(value)


class FinanceStatsOut(TZModel):
    """财务总览统计：按账户类型汇总余额。"""

    treasury: int
    peak_total: int
    user_total: int
    task_escrow_total: int
    issuance: int
    peak_count: int
    user_account_count: int

    @field_serializer(
        "treasury",
        "peak_total",
        "user_total",
        "task_escrow_total",
        "issuance",
    )
    def _money_str(self, value: int) -> str:
        return str(value)


class FinanceReversalCreate(BaseModel):
    """交易冲正：按原分录取反，一笔原交易只允许冲正一次。"""

    transaction_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=200)

    model_config = ConfigDict(extra="forbid")


class FinanceReversalOut(TZModel):
    transaction_id: int
    business_key: str
    amount: int
    original_transaction_id: int

    @field_serializer("amount")
    def _money_str(self, value: int) -> str:
        return str(value)


class FinancePeakTransferCreate(BaseModel):
    """峰间调拨：两侧峰账户加锁，禁止同峰。"""

    from_peak_id: int = Field(gt=0)
    to_peak_id: int = Field(gt=0)
    amount: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    reason: str = Field(min_length=1, max_length=200)

    model_config = ConfigDict(extra="forbid")
