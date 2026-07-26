from datetime import timedelta
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    InvalidCredentialsException,
    RateLimitException,
    UserAlreadyExistsException,
    UserNotActiveException,
)
from app.core.rate_limit import get_limiter
from app.core.security import (
    async_get_password_hash,
    async_verify_password,
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
from app.services.audit_service import AuditService

# 与 bcrypt 的正常工作因子一致；即使用户名不存在也执行一次验证，降低用户枚举的时序差异。
_DUMMY_PASSWORD_HASH = "$2b$12$4wW.7xG3E9HU7z3dlkl37u4CVbHfGfgjXVLYP2A0WcBAe3ZQojbPS"
_MICROSECONDS_PER_SECOND = 1_000_000


class AuthService:
    def __init__(self, db: AsyncSession, audit: Optional[AuditService] = None):
        self.db = db
        self.user_repo = UserRepository(db)
        self.refresh_repo = RefreshTokenRepository(db)
        # 审计服务构造函数注入（service 间调用只允许走注入依赖）。
        # 默认无 db 的 AuditService：record() 走独立会话，互不污染。
        self.audit = audit if audit is not None else AuditService()

    # ------------------------------------------------------------------ 认证

    async def authenticate(self, username: str, password: str) -> Optional[User]:
        """验证用户凭据"""
        user = await self.user_repo.get_by_username(username)
        if not user:
            await async_verify_password(password, _DUMMY_PASSWORD_HASH)
            return None
        if not await async_verify_password(password, user.hashed_password):
            return None
        return user

    async def login(self, username: str, password: str, client_meta: dict) -> TokenPair:
        """登录：账号级防爆破 → 验证凭据 → 检查激活 → 签发双 token。

        成功与失败都写审计（best-effort 独立会话，故障不阻断登录）；
        暴力破解溯源依赖登录失败事件。
        """
        # 账号级防爆破：仅按 IP 限流挡不住分布式撞库（多 IP 打同一账号）。
        # 成功登录也计入预算——真人登录频率远低于阈值，撞库脚本会迅速触顶。
        allowed = await get_limiter().is_allowed(
            f"ratelimit:auth_account:{username}",
            settings.AUTH_ACCOUNT_RATE_LIMIT_CALLS,
            settings.AUTH_ACCOUNT_RATE_LIMIT_PERIOD,
        )
        if not allowed:
            await self.audit.record(
                action="auth.login_rate_limited",
                resource_type="auth",
                detail={"username": username},
                **client_meta,
            )
            raise RateLimitException(
                message="登录尝试过于频繁，请稍后再试",
                limit=settings.AUTH_ACCOUNT_RATE_LIMIT_CALLS,
                window=settings.AUTH_ACCOUNT_RATE_LIMIT_PERIOD,
            )

        user = await self.authenticate(username, password)

        if not user:
            await self.audit.record(
                action="auth.login_failed",
                resource_type="auth",
                detail={"username": username},
                **client_meta,
            )
            raise InvalidCredentialsException()

        if not user.is_active:
            await self.audit.record(
                action="auth.login_failed",
                resource_type="auth",
                detail={"username": username, "reason": "user not active"},
                **client_meta,
            )
            raise UserNotActiveException(user_id=user.id)

        pair = await self.issue_token_pair(user)
        await self.audit.record(
            action="auth.login",
            resource_type="auth",
            resource_id=str(user.id),
            actor_id=user.id,
            actor_username=user.username,
            **client_meta,
        )
        return pair

    async def get_current_user(
        self, token: str, *, payload: Optional[dict] = None
    ) -> Optional[User]:
        """通过 access token 获取当前用户。调用方需自行处理黑名单检查。

        若 token 含 ``pwd_at`` 且用户 ``password_changed_at`` 已更新（改密），
        视为 token 失效（返回 None → 上层 401）。

        ``payload``：调用方已解码过的声明。鉴权链上同一个 token 会被多处使用
        （取用户 + 查黑名单），传入可省掉重复的签名校验；不传则就地解码。
        """
        if payload is None:
            payload = verify_token(token)
        if payload is None:
            return None

        username = payload.get("sub")
        if not isinstance(username, str):
            return None

        user = await self.user_repo.get_by_username(username)
        if user is None:
            return None
        # get_by_username 已排除软删；双保险
        if getattr(user, "deleted_at", None) is not None:
            return None

        # 改密后吊销旧 access：token 内 pwd_at 落后于用户当前 password_changed_at
        if user.password_changed_at is not None:
            token_pwd_at = payload.get("pwd_at")
            user_pwd_at = int(
                user.password_changed_at.timestamp() * _MICROSECONDS_PER_SECOND
            )
            if token_pwd_at is None or int(token_pwd_at) < user_pwd_at:
                return None

        return user

    # ------------------------------------------------------------------ 用户

    async def get_user(self, user_id: int) -> Optional[User]:
        """通过ID获取用户"""
        return await self.user_repo.get_by_id(user_id)

    async def create_user(
        self, user_data, is_superuser: bool = False, commit: bool = True
    ) -> User:
        """创建新用户（统一入口：查重 + 哈希密码 + 落库）。

        - user_data: 含 username/email/password 以及可选 full_name/is_active 的对象
          （schemas.auth.UserCreate 或同形态对象）。
        - is_superuser: 是否设为超级用户，默认 False。创建接口不应让请求体直接决定该字段。

        用户名/邮箱重复抛 UserAlreadyExistsException。
        """
        if await self.user_repo.get_by_username(user_data.username):
            raise UserAlreadyExistsException(username=user_data.username)

        if await self.user_repo.get_by_email(user_data.email):
            raise UserAlreadyExistsException(email=user_data.email)

        user_dict = {
            "username": user_data.username,
            "email": user_data.email,
            "hashed_password": await async_get_password_hash(user_data.password),
            # 未传则按模型默认（is_active 默认 True）
            "is_active": getattr(user_data, "is_active", True),
            "is_superuser": is_superuser,
        }
        # full_name 可选字段，存在才写入
        full_name = getattr(user_data, "full_name", None)
        if full_name is not None:
            user_dict["full_name"] = full_name

        try:
            user = await self.user_repo.create(user_dict)
            if commit:
                await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise UserAlreadyExistsException(username=user_data.username) from exc
        return user

    async def create_user_with_audit(
        self,
        user_data,
        *,
        actor: User,
        client_meta: dict,
        via: str,
    ) -> User:
        """创建用户 + 审计，同一事务原子提交（路由层唯一入口）。

        把「业务变更 + 审计 + commit」收敛到 service 层：路由只调这一个方法，
        不再各自组合 commit=False + record_atomic（漏配即静默丢数据）。
        """
        created = await self.create_user(user_data, is_superuser=False, commit=False)
        await self.audit.record_atomic(
            action="user.create",
            resource_type="user",
            resource_id=str(created.id),
            actor_id=actor.id,
            actor_username=actor.username,
            detail={"username": created.username, "via": via},
            **client_meta,
        )
        return created

    # ------------------------------------------------------------------ token 套件

    async def issue_token_pair(self, user: User) -> TokenPair:
        """登录成功时签发 access + refresh 双 token（refresh 落库）。"""
        access_token, jti, _expire = create_access_token(
            data=self._access_token_claims(user)
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
