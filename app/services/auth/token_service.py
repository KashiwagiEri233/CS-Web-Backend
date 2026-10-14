"""Token 套件服务：access/refresh 签发、轮换、撤销 + access 黑名单。

C-17 拆分第三切片：从 auth_service.py 抽出。token 域自包含
（签发/轮换/撤销/黑名单），认证流程通过 AuthService 组合调用。
"""

from datetime import timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import InvalidCredentialsException, UserNotActiveException
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    verify_token,
)
from app.core.security_blacklist import get_blacklist
from app.core.timezone import now_utc
from app.models.user import User
from app.repositories.refresh_token_repo import RefreshTokenRepository
from app.repositories.user_repo import UserRepository
from app.schemas.auth import TokenPair

# 与 bcrypt 的正常工作因子一致；即使用户名不存在也执行一次验证，降低用户枚举的时序差异。
_MICROSECONDS_PER_SECOND = 1_000_000


class TokenService:
    """access/refresh token 签发、轮换、撤销与黑名单校验。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.refresh_repo = RefreshTokenRepository(db)

    async def issue_token_pair(
        self,
        user: User,
        client_meta: Optional[dict] = None,
    ) -> TokenPair:
        """登录成功时签发 access + refresh 双 token（refresh 落库，附设备信息）。"""
        access_token, jti, _expire = create_access_token(
            data=self._access_token_claims(user)
        )

        refresh_plain = generate_refresh_token()
        refresh_hash = hash_refresh_token(refresh_plain)
        # 同一次登录的刷新链标识：首条 token 的哈希前缀作为 family_id
        family_id = refresh_hash[:32]
        client_meta = client_meta or {}
        await self.refresh_repo.create(
            user_id=user.id,
            token_hash=refresh_hash,
            family_id=family_id,
            expires_at=self._refresh_expire_at(),
            ip_address=client_meta.get("ip_address"),
            user_agent=client_meta.get("user_agent"),
        )
        await self.db.commit()

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_plain,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def refresh_access_token(self, refresh_token_plain: str) -> TokenPair:
        """用 refresh token 换取新的 access + refresh（rotation + 复用检测）。

        已撤销 token 在宽限窗口（REFRESH_TOKEN_ROTATION_LEEWAY_SECONDS）内再次被
        使用，视为客户端并发重试，允许继续轮换；超出窗口 → 视为泄漏 → family 失效。
        """
        token_hash = hash_refresh_token(refresh_token_plain)
        # 对当前 token 加行锁，确保同一 refresh token 的并发轮换只有一个成功；
        # 后到请求会在锁释放后看到 revoked_at：宽限窗口内按并发重试放行，
        # 超出窗口才触发 family 复用处置。
        rt = await self.refresh_repo.get_by_hash(token_hash, for_update=True)

        if rt is None:
            # token 不存在：可能是伪造，也可能是已被清理。统一报错，不做额外处置。
            raise InvalidCredentialsException(
                details={"reason": "invalid refresh token"}
            )

        if rt.revoked_at is not None:
            leeway = settings.REFRESH_TOKEN_ROTATION_LEEWAY_SECONDS
            revoked_age = (now_utc() - rt.revoked_at).total_seconds()
            within_leeway = leeway > 0 and revoked_age <= leeway
            if within_leeway:
                # 仅当 family 内仍存在活跃后继 token 时才视为轮换并发重试；
                # 整体撤销（改密/封禁/revoke_all）后 family 无活跃 token，按复用处置。
                within_leeway = await self.refresh_repo.family_has_active(rt.family_id)
            if not within_leeway:
                # 复用！family 内的已撤销 token 又出现，整条 family 立即吊销
                await self.refresh_repo.revoke_family(rt.family_id)
                await self.db.commit()
                raise InvalidCredentialsException(
                    details={"reason": "refresh token reuse detected; family revoked"}
                )
            # 宽限窗口内：视为客户端并发重试（多标签页/网络重试），允许继续轮换；
            # 不再 revoke 本行——避免刷新 revoked_at 导致宽限窗口被无限延长。

        if rt.expires_at is not None and now_utc() >= rt.expires_at:
            # 已过期自然失效
            raise InvalidCredentialsException(
                details={"reason": "refresh token expired"}
            )

        user = await self.user_repo.get_by_id(rt.user_id)
        # 软删 / 停用用户不得再签发 token
        if (
            user is None
            or not user.is_active
            or getattr(user, "deleted_at", None) is not None
        ):
            raise UserNotActiveException(user_id=rt.user_id)

        # 轮换：撤销当前 token，签发新 token（同 family）。
        # 宽限重试路径的本行已处于撤销态，跳过以免刷新 revoked_at 延长窗口。
        if rt.revoked_at is None:
            await self.refresh_repo.revoke(rt.id)

        new_access, _jti, _exp = create_access_token(
            data=self._access_token_claims(user)
        )
        new_refresh_plain = generate_refresh_token()
        new_refresh_hash = hash_refresh_token(new_refresh_plain)
        await self.refresh_repo.create(
            user_id=user.id,
            token_hash=new_refresh_hash,
            family_id=rt.family_id,  # 同一家族
            expires_at=self._refresh_expire_at(),
            ip_address=rt.ip_address,  # 轮换沿用设备信息
            user_agent=rt.user_agent,
        )
        await self.db.commit()

        return TokenPair(
            access_token=new_access,
            refresh_token=new_refresh_plain,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def revoke_refresh_token(self, refresh_token_plain: str) -> bool:
        """登出时撤销 refresh token。"""
        token_hash = hash_refresh_token(refresh_token_plain)
        rt = await self.refresh_repo.get_by_hash(token_hash)
        if rt is None:
            return False
        await self.refresh_repo.revoke(rt.id)
        await self.db.commit()
        return True

    async def revoke_all_user_tokens(self, user_id: int) -> int:
        """改密/封禁时撤销用户全部 refresh token。返回撤销条数。"""
        n = await self.refresh_repo.revoke_all_for_user(user_id)
        await self.db.commit()
        return n

    async def blacklist_access_token(self, token: str) -> bool:
        """把指定 access token 加入黑名单（登出用）。

        只在 token 仍有效时有意义；已过期的 token 自然失效，加入黑名单也只是无操作。
        返回 True 表示成功加入或本就过期；False 表示加入失败（不应阻塞登出流程）。
        """
        payload = verify_token(token)
        if payload is None:
            return True  # 无效 token 视作已失效

        jti = payload.get("jti")
        if not jti:
            return True

        exp = payload.get("exp")
        if exp is None:
            return True

        remain = int(exp - now_utc().timestamp())
        if remain <= 0:
            return True

        await get_blacklist().add(jti, remain)
        return True

    async def is_access_revoked(
        self, token: str, *, payload: Optional[dict] = None
    ) -> bool:
        """校验 access token 是否已被撤销（黑名单查询）。

        ``payload`` 同 ``get_current_user``：传入已解码声明可跳过重复签名校验。
        """
        if payload is None:
            payload = verify_token(token)
        if payload is None:
            return False  # 无效 token 交给上层 401
        jti = payload.get("jti")
        if not jti:
            return False
        return await get_blacklist().contains(jti)

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _access_token_claims(user: User) -> dict:
        """构造 access token 声明。

        写入 ``pwd_at``（password_changed_at 的 UTC 微秒时间戳）：
        校验时与用户当前 password_changed_at 对比，改密前签发的 token 立即失效。
        """
        claims: dict = {"sub": user.username, "id": user.id}
        password_changed_at = getattr(user, "password_changed_at", None)
        if password_changed_at is not None:
            claims["pwd_at"] = int(
                password_changed_at.timestamp() * _MICROSECONDS_PER_SECOND
            )
        return claims

    @staticmethod
    def _refresh_expire_at():
        return now_utc() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
