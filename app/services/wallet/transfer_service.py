"""用户钱包转账编排：本人扣款、收款人校验、幂等重放。"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    ConflictException,
    ErrorCode,
    NotFoundException,
    ValidationException,
)
from app.core.timezone import now_utc
from app.models.user import User
from app.repositories.wallet_repo import WalletRepository
from app.services.wallet.idempotency_service import canonical_request_hash
from app.services.wallet.ledger_service import LedgerService

IDEMPOTENCY_OPERATION = "wallet_transfer"
_IDEMPOTENCY_KEY_MAX_LEN = 120


class WalletTransferService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = WalletRepository(db)
        self.ledger = LedgerService(db)

    async def _get_active_user(self, user_id: int) -> User:
        result = await self.db.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundException(
                message="收款用户不存在", resource_type="user", resource_id=user_id
            )
        if not user.is_active:
            raise ValidationException(message="收款用户已停用")
        return user

    async def transfer(
        self,
        *,
        actor: User,
        recipient_user_id: int,
        amount_text: str,
        remark: Optional[str],
        related_task_id: Optional[int],
        idempotency_key: Optional[str],
        request_id: Optional[str],
    ) -> dict:
        """执行本人钱包转账；返回可直接作为 HTTP 响应的字段。"""
        if not idempotency_key:
            raise ValidationException(
                message="缺少 Idempotency-Key",
                details={"header": "Idempotency-Key"},
            )
        if len(idempotency_key) > _IDEMPOTENCY_KEY_MAX_LEN:
            raise ValidationException(message="Idempotency-Key 过长")
        if recipient_user_id == actor.id:
            raise ValidationException(message="不能转给自己")

        amount = int(amount_text)
        if amount <= 0:
            raise ValidationException(
                message="金额必须为正整数",
                error_code=ErrorCode.Validation.INVALID_MONEY_AMOUNT,
            )
        if amount > settings.WALLET_MAX_TRANSFER_AMOUNT:
            raise ValidationException(
                message="金额超过单笔上限",
                error_code=ErrorCode.Validation.INVALID_MONEY_AMOUNT,
                details={"max": settings.WALLET_MAX_TRANSFER_AMOUNT},
            )

        recipient = await self._get_active_user(recipient_user_id)

        request_hash = canonical_request_hash(
            {
                "actor_id": actor.id,
                "recipient_user_id": recipient_user_id,
                "amount": amount,
                "remark": remark or "",
                "related_task_id": related_task_id,
            }
        )
        existing = await self.repo.get_idempotency_record(
            actor.id, IDEMPOTENCY_OPERATION, idempotency_key
        )
        if existing is not None:
            if existing.canonical_request_hash != request_hash:
                raise ConflictException(
                    message="相同 Idempotency-Key 的请求内容不一致",
                    error_code=ErrorCode.Conflict.IDEMPOTENCY_KEY_REUSED,
                )
            return {**dict(existing.response_body or {}), "_replayed": True}

        from_account = await self.ledger.ensure_user_account(actor.id)
        to_account = await self.ledger.ensure_user_account(recipient.id)

        tx, _entries = await self.ledger.transfer(
            from_account_id=from_account.id,
            to_account_id=to_account.id,
            amount=amount,
            type="user_transfer",
            business_key=f"transfer:{idempotency_key}",
            actor_user_id=actor.id,
            reason=remark,
            related_task_id=related_task_id,
            request_id=request_id,
            source_type=IDEMPOTENCY_OPERATION,
            source_id=idempotency_key,
        )

        response = {
            "transaction_id": tx.id,
            "business_key": tx.business_key,
            "from_account_id": from_account.id,
            "to_account_id": to_account.id,
            "amount": str(amount),
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
            "_replayed": False,
        }
        await self.repo.create_idempotency_record(
            {
                "actor_id": actor.id,
                "operation": IDEMPOTENCY_OPERATION,
                "key": idempotency_key,
                "canonical_request_hash": request_hash,
                "status_code": 200,
                "response_body": response,
                "expires_at": now_utc()
                + timedelta(seconds=settings.IDEMPOTENCY_RECORD_TTL_SECONDS),
            }
        )
        return response

    async def list_recipients(self, query: str, limit: int = 10) -> list[dict]:
        """按用户名/展示名精确或前缀搜索收款人；最小披露，不含邮箱/学号。"""
        keyword = query.strip()
        if len(keyword) < 3:
            raise ValidationException(message="搜索关键词至少 3 个字符")
        stmt = (
            select(User)
            .where(
                User.deleted_at.is_(None),
                User.is_active.is_(True),
                (User.username.ilike(f"{keyword}%"))
                | (User.display_name.ilike(f"%{keyword}%")),
            )
            .order_by(User.id)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        users = result.scalars().all()
        return [
            {
                "user_id": user.id,
                "display_name": user.display_name or user.username,
                "username": user.username,
            }
            for user in users
        ]
