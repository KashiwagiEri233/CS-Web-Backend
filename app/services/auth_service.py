from datetime import timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    InvalidCredentialsException,
    UserAlreadyExistsException,
    UserNotActiveException,
)
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    verify_password,
    verify_token,
)
from app.core.security_blacklist import get_blacklist
from app.models.user import User
from app.repositories.refresh_token_repo import RefreshTokenRepository
from app.repositories.user_repo import UserRepository
from app.schemas.auth import TokenPair


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.refresh_repo = RefreshTokenRepository(db)

    # ------------------------------------------------------------------ 认证

    async def authenticate(self, username: str, password: str) -> Optional[User]:
        """验证用户凭据"""
        user = await self.user_repo.get_by_username(username)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    async def get_current_user(self, token: str) -> Optional[User]:
        """通过 access token 获取当前用户。调用方需自行处理黑名单检查。"""
        payload = verify_token(token)
        if payload is None:
            return None

        username: str = payload.get("sub")
        if username is None:
            return None

        return await self.user_repo.get_by_username(username)

    # ------------------------------------------------------------------ 用户

    async def get_user(self, user_id: int) -> Optional[User]:
        """通过ID获取用户"""
        return await self.user_repo.get_by_id(user_id)

    async def create_user(self, user_data):
        """创建新用户"""
        from app.core.security import get_password_hash

        if await self.user_repo.get_by_username(user_data.username):
            raise UserAlreadyExistsException(username=user_data.username)

        if await self.user_repo.get_by_email(user_data.email):
            raise UserAlreadyExistsException(email=user_data.email)

        hashed_password = get_password_hash(user_data.password)
        user_dict = {
            "username": user_data.username,
            "email": user_data.email,
            "hashed_password": hashed_password,
            "is_active": True,
        }
        return await self.user_repo.create(user_dict)

    # ------------------------------------------------------------------ token 套件

    async def issue_token_pair(self, user: User) -> TokenPair:
        """登录成功时签发 access + refresh 双 token（refresh 落库）。"""
        access_token, jti, _expire = create_access_token(
            data={"sub": user.username, "id": user.id}
        )

        refresh_plain = generate_refresh_token()
        refresh_hash = hash_refresh_token(refresh_plain)
        # 同一次登录的刷新链标识：首条 token 的哈希前缀作为 family_id
        family_id = refresh_hash[:32]
        await self.refresh_repo.create(
            user_id=user.id,
            token_hash=refresh_hash,
            family_id=family_id,
            expires_at=self._refresh_expire_at(),
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

        检测到已撤销的 token 再次被使用 → 视为泄漏 → 整个 family 立即失效。
        """
        token_hash = hash_refresh_token(refresh_token_plain)
        rt = await self.refresh_repo.get_by_hash(token_hash)

        if rt is None:
            # token 不存在：可能是伪造，也可能是已被清理。统一报错，不做额外处置。
            raise InvalidCredentialsException(details={"reason": "invalid refresh token"})

        if rt.revoked_at is not None:
            # 复用！family 内的已撤销 token 又出现，整条 family 立即吊销
            await self.refresh_repo.revoke_family(rt.family_id)
            await self.db.commit()
            raise InvalidCredentialsException(
                details={"reason": "refresh token reuse detected; family revoked"}
            )

        if not rt.is_active:
            # 已过期自然失效
            raise InvalidCredentialsException(
                details={"reason": "refresh token expired"}
            )

        user = await self.user_repo.get_by_id(rt.user_id)
        if user is None or not user.is_active:
            raise UserNotActiveException(user_id=rt.user_id)

        # 轮换：撤销当前 token，签发新 token（同 family）
        await self.refresh_repo.revoke(rt.id)

        new_access, _jti, _exp = create_access_token(
            data={"sub": user.username, "id": user.id}
        )
        new_refresh_plain = generate_refresh_token()
        new_refresh_hash = hash_refresh_token(new_refresh_plain)
        await self.refresh_repo.create(
            user_id=user.id,
            token_hash=new_refresh_hash,
            family_id=rt.family_id,  # 同一家族
            expires_at=self._refresh_expire_at(),
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

    # ------------------------------------------------------------------ access 黑名单

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

        from datetime import datetime, timezone

        remain = int(exp - datetime.now(timezone.utc).timestamp())
        if remain <= 0:
            return True

        await get_blacklist().add(jti, remain)
        return True

    async def is_access_revoked(self, token: str) -> bool:
        """校验 access token 是否已被撤销（黑名单查询）。"""
        payload = verify_token(token)
        if payload is None:
            return False  # 无效 token 交给上层 401
        jti = payload.get("jti")
        if not jti:
            return False
        return await get_blacklist().contains(jti)

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _refresh_expire_at():
        from datetime import datetime, timezone

        return datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )
