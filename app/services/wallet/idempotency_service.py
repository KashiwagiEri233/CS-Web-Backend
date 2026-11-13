"""写动作幂等编排：canonical 摘要、重放与落库。

约定：
- 同键同内容返回首次成功响应（附 `_replayed=True`）；同键异内容 409。
- 业务失败随外层事务回滚，不留下「处理中」悬挂记录。
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi.encoders import jsonable_encoder

from app.core.config import settings
from app.core.exceptions import ConflictException, ErrorCode, ValidationException
from app.core.timezone import now_utc
from app.repositories.wallet_repo import WalletRepository

IDEMPOTENCY_KEY_MAX_LEN = 120


def canonical_request_hash(payload: dict) -> str:
    """稳定排序 + SHA256；不包含 Cookie/Token/密码。"""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def require_idempotency_key(key: Optional[str]) -> str:
    if not key:
        raise ValidationException(
            message="缺少 Idempotency-Key", details={"header": "Idempotency-Key"}
        )
    if len(key) > IDEMPOTENCY_KEY_MAX_LEN:
        raise ValidationException(message="Idempotency-Key 过长")
    return key


class IdempotencyService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = WalletRepository(db)

    async def replay(
        self, *, actor_id: int, operation: str, key: str, payload: dict
    ) -> Optional[dict]:
        """若键已存在：同内容返回旧响应；异内容抛 409；不存在返回 None。"""
        existing = await self.repo.get_idempotency_record(actor_id, operation, key)
        if existing is None:
            return None
        if existing.canonical_request_hash != canonical_request_hash(payload):
            raise ConflictException(
                message="相同 Idempotency-Key 的请求内容不一致",
                error_code=ErrorCode.Conflict.IDEMPOTENCY_KEY_REUSED,
            )
        return {**dict(existing.response_body or {}), "_replayed": True}

    async def save(
        self,
        *,
        actor_id: int,
        operation: str,
        key: str,
        payload: dict,
        response: dict,
        status_code: int = 200,
    ) -> None:
        await self.repo.create_idempotency_record(
            {
                "actor_id": actor_id,
                "operation": operation,
                "key": key,
                "canonical_request_hash": canonical_request_hash(payload),
                "status_code": status_code,
                "response_body": jsonable_encoder(response),
                "expires_at": now_utc()
                + timedelta(seconds=settings.IDEMPOTENCY_RECORD_TTL_SECONDS),
            }
        )
