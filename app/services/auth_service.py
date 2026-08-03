from datetime import timedelta
import re
import secrets
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AuthenticationException,
    BusinessException,
    ConflictException,
    ErrorCode,
    InvalidCredentialsException,
    RateLimitException,
    UserAlreadyExistsException,
    UserNotActiveException,
    ValidationException,
)
from app.core.password_compat import needs_rehash, verify_password_any
from app.core.rate_limit import get_limiter
from app.core.security import (
    async_get_password_hash,
    async_verify_password,
    create_access_token,
    create_two_factor_token,
    generate_refresh_token,
    hash_refresh_token,
    verify_token,
    verify_two_factor_token,
)
from app.core.security_blacklist import get_blacklist
from app.core.timezone import now_utc
from app.models.user import User
from app.repositories.login_history_repo import LoginHistoryRepository
from app.repositories.password_history_repo import PasswordHistoryRepository
from app.repositories.refresh_token_repo import RefreshTokenRepository
from app.repositories.user_repo import UserRepository
from app.schemas.auth import TokenPair
from app.services.audit_service import AuditService
from app.services.totp_service import TOTPService

# 与 bcrypt 的正常工作因子一致；即使用户名不存在也执行一次验证，降低用户枚举的时序差异。
_DUMMY_PASSWORD_HASH = "$2b$12$4wW.7xG3E9HU7z3dlkl37u4CVbHfGfgjXVLYP2A0WcBAe3ZQojbPS"
_MICROSECONDS_PER_SECOND = 1_000_000


def derive_username(email: str) -> str:
    """从前端邮箱派生后端 username（前端 users 表无 username 列）。

    规则：邮箱本地部分清洗为 [a-zA-Z0-9_-]，保底 3 字符、上限 50 字符；
    数字开头补 'u' 前缀。冲突（罕见）由调用方追加数字后缀。
    """
    local = email.split("@")[0]
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", local)
    if not cleaned:
        cleaned = "user"
    if cleaned[0].isdigit():
        cleaned = f"u{cleaned}"
    if len(cleaned) < 3:
        cleaned = cleaned.ljust(3, "_")
    return cleaned[:50]


class AuthService:
    def __init__(self, db: AsyncSession, audit: Optional[AuditService] = None):
        self.db = db
        self.user_repo = UserRepository(db)
        self.refresh_repo = RefreshTokenRepository(db)
        self.login_history_repo = LoginHistoryRepository(db)
        self.password_history_repo = PasswordHistoryRepository(db)
        self.totp_service = TOTPService(db)
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

    async def authenticate_by_email(
        self, email: str, password: str
    ) -> tuple[Optional[User], bool]:
        """按邮箱验证凭据（前端登录主路径）。

        返回 (user, needs_rehash)：user 为空 = 凭据错误；needs_rehash 表示
        旧 scrypt 哈希验证通过、需要懒升级为 bcrypt（OQ-5，见 app/core/password_compat.py）。
        """
        user = await self.user_repo.get_by_email(email)
        if not user:
            # 用户不存在也执行一次等价验证，均衡时序防邮箱枚举
            await async_verify_password(password, _DUMMY_PASSWORD_HASH)
            return None, False
        if not await self._verify_password_compat(password, user.hashed_password):
            return None, False
        return user, needs_rehash(user.hashed_password)

    async def _verify_password_compat(self, password: str, stored: str) -> bool:
        """bcrypt（新）或 scrypt（旧，迁移窗口）哈希均可验证；超长输入返回 False。"""
        import asyncio

        return await asyncio.to_thread(verify_password_any, password, stored)

    async def _lazy_upgrade_password(
        self, user: User, password: str, needs: bool
    ) -> None:
        """scrypt 旧哈希验证通过后懒升级为 bcrypt（随登录事务提交）。"""
        if not needs:
            return
        user.hashed_password = await async_get_password_hash(password)
        user.updated_at = now_utc()

    async def _record_login_history(
        self,
        *,
        user_id: Optional[int],
        success: bool,
        attempted_email: Optional[str] = None,
        **meta: str,
    ) -> None:
        await self.login_history_repo.create(
            user_id=user_id,
            ip=meta.get("ip_address"),
            user_agent=meta.get("user_agent"),
            success=success,
            attempted_email=attempted_email,
        )

    async def login_by_email(
        self, email: str, password: str, client_meta: dict
    ) -> dict:
        """邮箱登录：返回 ``{requires_2fa, two_factor_token, pair}``。

        - 2FA 未启用：直接签发双 token
        - 2FA 已启用：返回 2FA 预认证 token，需走 complete_two_factor_login
        - 登录成功/失败均写登录历史（登录历史与异常告警能力）
        """
        normalized = email.lower()

        # 账号级防爆破（按邮箱计数，与既有 username 流程同策略）
        allowed = await get_limiter().is_allowed(
            f"ratelimit:auth_account:{normalized}",
            settings.AUTH_ACCOUNT_RATE_LIMIT_CALLS,
            settings.AUTH_ACCOUNT_RATE_LIMIT_PERIOD,
        )
        if not allowed:
            await self.audit.record(
                action="auth.login_rate_limited",
                resource_type="auth",
                detail={"email": normalized},
                **client_meta,
            )
            raise RateLimitException(
                message="登录尝试过于频繁，请稍后再试",
                limit=settings.AUTH_ACCOUNT_RATE_LIMIT_CALLS,
                window=settings.AUTH_ACCOUNT_RATE_LIMIT_PERIOD,
            )

        user, needs_rehash_flag = await self.authenticate_by_email(normalized, password)
        if user is None:
            await self._record_login_history(
                user_id=None, success=False, attempted_email=normalized, **client_meta
            )
            await self.audit.record(
                action="auth.login_failed",
                resource_type="auth",
                detail={"email": normalized},
                **client_meta,
            )
            raise InvalidCredentialsException()

        if not user.is_active:
            await self._record_login_history(
                user_id=user.id,
                success=False,
                attempted_email=normalized,
                **client_meta,
            )
            raise UserNotActiveException(user_id=user.id)

        await self._lazy_upgrade_password(user, password, needs_rehash_flag)
        await self.db.commit()

        if await self.totp_service.is_enabled(user.id):
            token, _jti = create_two_factor_token(
                user.id, settings.TOTP_PRE_AUTH_TTL_MINUTES
            )
            return {"requires_2fa": True, "two_factor_token": token, "pair": None}

        pair = await self.issue_token_pair(user, client_meta)
        await self._record_login_history(user_id=user.id, success=True, **client_meta)
        await self.db.commit()
        return {"requires_2fa": False, "two_factor_token": None, "pair": pair}

    async def complete_two_factor_login(
        self, two_factor_token: str, code: str, client_meta: dict
    ) -> TokenPair:
        """2FA 第二步：校验预认证 token（一次性）→ 校验 TOTP/备用码 → 签发双 token。"""
        payload = verify_two_factor_token(two_factor_token)
        if payload is None:
            raise AuthenticationException(
                message="2FA 预认证凭证无效或已过期",
                error_code=ErrorCode.Auth.TWO_FACTOR_REQUIRED,
            )

        jti = payload.get("jti")
        # 防重放：同一 jti 只能消费一次（黑名单按剩余 TTL 记录）
        if jti and await get_blacklist().contains(jti):
            raise AuthenticationException(
                message="2FA 预认证凭证已被使用",
                error_code=ErrorCode.Auth.TWO_FACTOR_REQUIRED,
            )

        user_id = int(payload.get("sub", 0))
        user = await self.user_repo.get_by_id(user_id)
        if user is None or not user.is_active:
            raise UserNotActiveException(user_id=user_id)

        exp = payload.get("exp")
        remain = int(exp - now_utc().timestamp()) if exp else 0
        if remain > 0 and jti:
            await get_blacklist().add(jti, remain)

        if not await self.totp_service.verify(user.id, code):
            raise ValidationException(
                message="验证码错误", error_code=ErrorCode.Auth.TOTP_INVALID
            )

        pair = await self.issue_token_pair(user, client_meta)
        await self._record_login_history(user_id=user.id, success=True, **client_meta)
        await self.db.commit()
        return pair

    async def register(self, email: str, password: str, client_meta: dict) -> TokenPair:
        """注册（邮箱 + 密码，验证码在路由层校验）：创建用户并自动登录。"""
        normalized = email.lower()
        if await self.user_repo.get_by_email(normalized):
            raise ConflictException(
                message="该邮箱已被注册", error_code=ErrorCode.Conflict.EMAIL_EXISTS
            )

        base_username = derive_username(normalized)
        username = base_username
        for suffix in range(1, 100):
            if not await self.user_repo.get_by_username(username):
                break
            username = f"{base_username[:40]}_{suffix}"

        user_dict = {
            "username": username,
            "email": normalized,
            "hashed_password": await async_get_password_hash(password),
            "is_active": True,
            "is_superuser": False,
        }
        try:
            user = await self.user_repo.create(user_dict)
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictException(
                message="该邮箱已被注册", error_code=ErrorCode.Conflict.EMAIL_EXISTS
            ) from exc

        await self._record_login_history(user_id=user.id, success=True, **client_meta)
        await self.audit.record(
            action="auth.register",
            resource_type="auth",
            resource_id=str(user.id),
            detail={"email": normalized, "via": "email"},
            **client_meta,
        )
        pair = await self.issue_token_pair(user, client_meta)
        # 业务事件：注册成功 → 欢迎通知（订阅者自带会话，事务已提交）
        from app.core.events import event_bus

        event_bus.emit("user.registered", user_id=user.id)
        return pair

    async def login_with_github(self, info: dict, client_meta: dict) -> dict:
        """GitHub OAuth 登录/注册（回调验证后调用）。

        语义与前端一致（oauth.ts）：
        - 已按 github_id 绑定 → 直接登录
        - github 邮箱已注册但未绑定 → 不自动绑定（防账号接管）→ GITHUB_EMAIL_CONFLICT
        - 新用户 → 随机密码 + 资料字段落库（用户可走忘记密码或改密）
        返回与 login_by_email 相同的 {requires_2fa, two_factor_token, pair}。
        """
        github_id = info["github_id"]
        email = info["email"].lower()

        user = await self.user_repo.get_by_github_id(github_id)
        if user is None:
            existing = await self.user_repo.get_by_email(email)
            if existing is not None:
                raise ConflictException(
                    message="该邮箱已注册，请使用密码登录后手动绑定 GitHub",
                    error_code=ErrorCode.Auth.GITHUB_EMAIL_CONFLICT,
                )
            random_password = secrets.token_hex(16)
            base_username = derive_username(email)
            username = base_username
            for suffix in range(1, 100):
                if not await self.user_repo.get_by_username(username):
                    break
                username = f"{base_username[:40]}_{suffix}"
            user = await self.user_repo.create(
                {
                    "username": username,
                    "email": email,
                    "hashed_password": await async_get_password_hash(random_password),
                    "display_name": info.get("name") or None,
                    "avatar_url": info.get("avatar_url") or None,
                    "avatar_type": "github",
                    "github_url": info.get("html_url") or None,
                    "github_id": github_id,
                    "is_active": True,
                    "is_superuser": False,
                }
            )
            await self.db.commit()
            await self.audit.record(
                action="auth.oauth_register",
                resource_type="auth",
                resource_id=str(user.id),
                detail={"email": email, "via": "github"},
                **client_meta,
            )
        elif not user.is_active:
            raise UserNotActiveException(user_id=user.id)

        await self._record_login_history(user_id=user.id, success=True, **client_meta)
        await self.db.commit()

        if await self.totp_service.is_enabled(user.id):
            token, _jti = create_two_factor_token(
                user.id, settings.TOTP_PRE_AUTH_TTL_MINUTES
            )
            return {"requires_2fa": True, "two_factor_token": token, "pair": None}

        pair = await self.issue_token_pair(user, client_meta)
        return {"requires_2fa": False, "two_factor_token": None, "pair": pair}

    async def change_password(
        self, user_id: int, old_password: str, new_password: str
    ) -> None:
        """自助改密：旧密码校验 → 历史复用检测 → 重哈希 → 撤销全部 refresh token。

        旧 access token 由 JWT pwd_at 声明自动失效（见 get_current_user）。
        """
        user = await self.user_repo.get_by_id(user_id)
        if user is None or not await self._verify_password_compat(
            old_password, user.hashed_password
        ):
            raise BusinessException(
                message="当前密码不正确",
                error_code=ErrorCode.Auth.INVALID_CURRENT_PASSWORD,
            )

        limit = settings.PASSWORD_HISTORY_LIMIT
        if limit > 0:
            recent = await self.password_history_repo.recent_hashes(user_id, limit)
            for stored in recent:
                if await self._verify_password_compat(new_password, stored):
                    raise BusinessException(
                        message="新密码与最近使用过的密码重复",
                        error_code=ErrorCode.Auth.PASSWORD_IN_HISTORY,
                    )

        await self.password_history_repo.create(user_id, user.hashed_password)
        user.hashed_password = await async_get_password_hash(new_password)
        user.password_changed_at = now_utc()
        user.updated_at = now_utc()
        await self.refresh_repo.revoke_all_for_user(user_id)
        await self.db.commit()
        await self.password_history_repo.prune(user_id, limit)

    async def get_me(self, user_id: int) -> dict:
        """当前用户完整信息：用户 + 角色 + 2FA 状态。"""
        user = await self.user_repo.get_user_with_roles(user_id)
        if user is None:
            raise UserNotActiveException(user_id=user_id)
        two_factor_enabled = await self.totp_service.is_enabled(user_id)
        return {
            "user": user,
            "roles": [role.name for role in user.roles],
            "two_factor_enabled": two_factor_enabled,
        }

    async def list_sessions(self, user_id: int) -> list:
        """设备列表：未撤销且未过期的 refresh token（含 ip/user_agent）。"""
        tokens = await self.refresh_repo.list_active_for_user(user_id)
        return [
            {
                "id": token.id,
                "ip_address": token.ip_address,
                "user_agent": token.user_agent,
                "created_at": token.created_at,
                "expires_at": token.expires_at,
                "family_id": token.family_id[:12],  # 同族（同一次登录）标记
            }
            for token in tokens
        ]

    async def revoke_session(self, user_id: int, token_id: int) -> bool:
        """远程登出：撤销指定 refresh token（须属于该用户）。"""
        revoked = await self.refresh_repo.revoke_by_id_for_user(token_id, user_id)
        await self.db.commit()
        return revoked

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

        pair = await self.issue_token_pair(user, client_meta)
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
