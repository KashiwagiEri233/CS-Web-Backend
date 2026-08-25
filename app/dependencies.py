from typing import Optional

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AuthenticationException,
    UserNotActiveException,
)
from app.core.loguru_logger import set_logging_context
from app.core.security import verify_token
from app.database import get_db
from app.models.user import User
from app.services.auth.auth_service import AuthService

# OAuth2密码流。auto_error=False：缺 token 时返回 None 而非自动 401，
# 以便 AUTH_ENABLED=False 时整条链路可被旁路。
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False
)


def _auth_bypass_user() -> User:
    """AUTH_ENABLED=False 时返回的虚构超级用户（不持久化、仅存在于请求内）。"""
    return User(
        id=0,
        username="auth-bypass",
        email="bypass@local.dev",  # 合法邮箱格式，避免 EmailStr 校验报错
        full_name="Auth Bypass (DEV)",
        hashed_password="",
        is_active=True,
        is_superuser=True,
    )


async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """获取当前用户的依赖项。AUTH_ENABLED=False 时直接放行为超级用户。

    统一抛 BaseAppException 子类（而非 HTTPException），使响应走全局 ErrorResponse
    体系（含 traceback_id），并自动携带 OAuth2 规范要求的 WWW-Authenticate 头。
    """
    if not settings.AUTH_ENABLED:
        user = _auth_bypass_user()
        request.state.user_id = user.id
        set_logging_context(user_id=user.id)
        return user

    if token is None:
        raise AuthenticationException(message="无法验证凭据")

    # 签名校验只做一次：解码结果同时供取用户与黑名单查询复用（鉴权是每请求热路径）。
    payload = verify_token(token)
    if payload is None:
        raise AuthenticationException(message="无法验证凭据")

    auth_service = AuthService(db)
    authenticated_user = await auth_service.get_current_user(token, payload=payload)

    if authenticated_user is None:
        raise AuthenticationException(message="无法验证凭据")

    # 黑名单检查：登出/改密后让未过期 access token 立即失效
    if await auth_service.is_access_revoked(token, payload=payload):
        raise AuthenticationException(
            message="令牌已被撤销",
            details={"reason": "revoked"},
        )

    request.state.user_id = authenticated_user.id
    set_logging_context(user_id=authenticated_user.id)
    return authenticated_user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """获取当前活跃用户"""
    if not current_user.is_active:
        raise UserNotActiveException(user_id=current_user.id)
    return current_user


async def get_optional_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """可选用户依赖：未登录 / token 无效时返回 None，而非抛 401。

    用于"可选登录"场景——如 2FA 登录第二步（此刻用户只有预认证 token，
    尚未持有 access token）与社区匿名浏览（登录则附带身份）。直接声明
    ``Optional[User] = Depends(get_current_active_user)`` 不可行：FastAPI
    会在进入路由前解析依赖，而 ``get_current_user`` 对缺失 token 抛
    AuthenticationException，导致请求在函数体前就以 401 失败。
    """
    try:
        return await get_current_user(request, token=token, db=db)
    except AuthenticationException:
        return None
