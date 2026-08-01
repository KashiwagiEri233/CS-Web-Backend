"""邮箱验证码服务：6 位数字，HMAC-SHA256 哈希存储，TTL 内一次性有效。

与前端语义一致（src/modules/auth/server/verification-code.ts）：
- HMAC 而非慢哈希，避免验证码场景的 DoS 放大（验证码空间小 + 限流已足够）
- 发新码前作废该邮箱全部旧码；校验成功即标记 used 防重放
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ErrorCode, ValidationException
from app.core.timezone import now_utc
from app.models.verification_code import VerificationCode
from app.repositories.verification_code_repo import VerificationCodeRepository
from app.services.email_service import send_verification_code


def _hmac_secret() -> bytes:
    # 复用 SECRET_KEY（与前端复用 AUTH_SESSION_SECRET 同模式）；DB 泄露也无法反推验证码
    return (settings.SECRET_KEY or "").encode("utf-8")


def _hash_code(code: str) -> str:
    return hmac.new(_hmac_secret(), code.encode("utf-8"), hashlib.sha256).hexdigest()


def _verify_hash_code(code: str, stored: str) -> bool:
    actual = _hash_code(code)
    if len(actual) != len(stored):
        return False
    return hmac.compare_digest(actual, stored)


class VerificationService:
    """邮箱验证码：生成（含邮件发送）与校验。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = VerificationCodeRepository(db)

    async def generate(self, email: str) -> str:
        """生成 6 位验证码：作废旧码 → 生成 + 落库 → 发邮件。返回明文（仅日志用）。"""
        normalized = email.lower()
        await self.repo.invalidate_for_email(normalized)

        code = f"{secrets.randbelow(900000) + 100000}"  # 100000-999999
        code_hash = _hash_code(code)
        expires_at = now_utc() + timedelta(
            minutes=settings.VERIFICATION_CODE_TTL_MINUTES
        )
        await self.repo.create(normalized, code_hash, expires_at)
        await self.db.commit()

        await send_verification_code(normalized, code)
        return code

    async def verify(self, email: str, code: str) -> bool:
        """校验验证码：成功即标记 used（一次性）。"""
        normalized = email.lower()
        record: Optional[VerificationCode] = await self.repo.get_latest_unused(
            normalized, now_utc()
        )
        if record is None:
            return False
        if not _verify_hash_code(code, record.code_hash):
            return False
        await self.repo.mark_used(record.id)
        await self.db.commit()
        return True

    async def verify_or_raise(self, email: str, code: str) -> None:
        """校验失败抛 ValidationException（VERIFICATION_CODE_INVALID）。"""
        if not await self.verify(email, code):
            raise ValidationException(
                message="验证码错误或已过期",
                error_code=ErrorCode.Validation.VERIFICATION_CODE_INVALID,
            )
