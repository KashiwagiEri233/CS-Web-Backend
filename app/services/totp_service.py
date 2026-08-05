"""TOTP 双因素认证服务：setup / confirm / verify / disable / backup codes。

- secret 用与前端同算法（HKDF-SHA256 + AES-256-GCM）加密存储（app/core/totp_encryption.py）
- 备用码：新码用 bcrypt 哈希，旧码（scrypt 哈希）由 password_compat 兼容验证
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import totp as totp_core
from app.core import totp_encryption
from app.core.config import settings
from app.core.exceptions import ErrorCode, ValidationException
from app.core.password_compat import is_bcrypt_hash, verify_password_any
from app.core.security import async_get_password_hash, async_verify_password
from app.core.timezone import now_utc
from app.models.two_factor_auth import TwoFactorAuth
from app.repositories.two_factor_auth_repo import TwoFactorAuthRepository


class TOTPService:
    """2FA 业务逻辑。repo 只 flush，本服务显式 commit。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TwoFactorAuthRepository(db)

    # ------------------------------------------------------------------ 查询

    async def is_enabled(self, user_id: int) -> bool:
        record = await self.repo.get(user_id)
        return record is not None and record.enabled

    async def is_setup(self, user_id: int) -> bool:
        return await self.repo.get(user_id) is not None

    # ------------------------------------------------------------------ 设置流程

    async def setup(self, user_id: int, email: str) -> dict:
        """初始化 2FA：生成 secret + otpauth URI + 备用码（未启用，待 confirm）。"""
        secret = totp_core.generate_secret()
        otpauth_uri = totp_core.generate_otpauth_uri(
            email, secret, settings.TOTP_ISSUER
        )
        backup_codes = totp_core.generate_backup_codes()
        hashed_codes = await self._hash_backup_codes(backup_codes)

        encrypted = totp_encryption.encrypt_secret(secret)
        await self.repo.upsert_pending(user_id, encrypted, hashed_codes)
        await self.db.commit()

        return {
            "secret": secret,
            # 返回 snake_case，与 TwoFactorSetupResponse（camel_config → otpauthUri）对齐；
            # 此前用 otpauthURI 导致 response_model 缺字段 → 500。
            "otpauth_uri": otpauth_uri,
            "backup_codes": backup_codes,
        }

    async def confirm(self, user_id: int, code: str) -> None:
        """确认启用：校验 TOTP 码后激活。"""
        record = await self.repo.get(user_id)
        if record is None:
            raise ValidationException(
                message="请先初始化 2FA 设置",
                error_code=ErrorCode.Auth.TWO_FACTOR_NOT_SETUP,
            )
        if record.enabled:
            raise ValidationException(
                message="2FA 已启用",
                error_code=ErrorCode.Auth.TWO_FACTOR_ALREADY_ENABLED,
            )
        secret = totp_encryption.decrypt_secret(record.secret_encrypted)
        if not self._verify_totp(secret, code):
            raise ValidationException(
                message="验证码错误",
                error_code=ErrorCode.Auth.TOTP_INVALID,
            )
        await self.repo.enable(record)
        await self.db.commit()

    # ------------------------------------------------------------------ 验证

    def verify_user_code(self, record: TwoFactorAuth, code: str) -> bool:
        """验证 TOTP 码或备用码；备用码验证通过即移除该码（一次性）。"""
        secret = totp_encryption.decrypt_secret(record.secret_encrypted)
        if self._verify_totp(secret, code):
            return True
        return False

    async def verify(self, user_id: int, code: str) -> bool:
        """登录校验：未启用 2FA 直接放行；否则 TOTP 或备用码其一通过即可。

        备用码为一次性：验证通过后从列表移除并落库。
        """
        record = await self.repo.get(user_id)
        if record is None or not record.enabled:
            return True  # 未启用，直接放行（与前端一致）

        if self.verify_user_code(record, code):
            return True

        # 备用码验证（兼容 bcrypt 新 / scrypt 旧两种哈希）
        backup_codes = list(record.backup_codes or [])
        for i, stored in enumerate(backup_codes):
            if await self._verify_backup_code(code, stored):
                backup_codes.pop(i)
                await self.repo.set_backup_codes(record, backup_codes)
                await self.db.commit()
                return True
        return False

    async def verify_or_raise(self, user_id: int, code: str) -> None:
        """验证失败抛 ValidationException（TOTP_INVALID）。"""
        if not await self.verify(user_id, code):
            raise ValidationException(
                message="验证码错误",
                error_code=ErrorCode.Auth.TOTP_INVALID,
            )

    # ------------------------------------------------------------------ 禁用 / 备用码

    async def disable(self, user_id: int, code: str) -> None:
        """禁用 2FA（需先通过当前 TOTP/备用码校验）。"""
        await self.verify_or_raise(user_id, code)
        await self.repo.delete(user_id)
        await self.db.commit()

    async def regenerate_backup_codes(self, user_id: int, code: str) -> list[str]:
        """重新生成备用码（需先通过当前 TOTP/备用码校验）。"""
        await self.verify_or_raise(user_id, code)
        record = await self.repo.get(user_id)
        if record is None:
            raise ValidationException(
                message="2FA 未启用",
                error_code=ErrorCode.Auth.TWO_FACTOR_NOT_SETUP,
            )
        new_codes = totp_core.generate_backup_codes()
        hashed_codes = await self._hash_backup_codes(new_codes)
        await self.repo.set_backup_codes(record, hashed_codes)
        await self.db.commit()
        return new_codes

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _verify_totp(secret: str, code: str) -> bool:
        return totp_core.verify_code(
            secret,
            code,
            int(now_utc().timestamp()),
            period=settings.TOTP_STEP_SECONDS,
            window_steps=settings.TOTP_WINDOW_STEPS,
        )

    @staticmethod
    async def _hash_backup_codes(codes: list[str]) -> list[str]:
        """备用码哈希：优先 bcrypt；列表为空时返回空。"""
        return [await async_get_password_hash(c) for c in codes]

    @staticmethod
    async def _verify_backup_code(code: str, stored: str) -> bool:
        """备用码验证：bcrypt（新）或 scrypt（旧，迁移窗口）均可。"""
        if is_bcrypt_hash(stored):
            return await async_verify_password(code, stored)
        import asyncio

        return await asyncio.to_thread(verify_password_any, code, stored)
