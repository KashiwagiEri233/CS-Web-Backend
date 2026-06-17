from typing import Optional

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AuthenticationException,
    PermissionDeniedException,
    UserNotActiveException,
)
from app.database import get_db
from app.models.user import User
from app.services.auth_service import AuthService

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
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """获取当前用户的依赖项。AUTH_ENABLED=False 时直接放行为超级用户。

    统一抛 BaseAppException 子类（而非 HTTPException），使响应走全局 ErrorResponse
    体系（含 traceback_id），并自动携带 OAuth2 规范要求的 WWW-Authenticate 头。
    """
    if not settings.AUTH_ENABLED:
        return _auth_bypass_user()

    if token is None:
        raise AuthenticationException(message="无法验证凭据")

    auth_service = AuthService(db)
    user = await auth_service.get_current_user(token)

    if user is None:
        raise AuthenticationException(message="无法验证凭据")

    # 黑名单检查：登出/改密后让未过期 access token 立即失效
    if await auth_service.is_access_revoked(token):
        raise AuthenticationException(
            message="令牌已被撤销",
            details={"reason": "revoked"},
        )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """获取当前活跃用户"""
    if not current_user.is_active:
        raise UserNotActiveException(user_id=current_user.id)
    return current_user


async def get_current_superuser(
    current_user: User = Depends(get_current_user)
) -> User:
    """获取当前超级用户"""
    if not current_user.is_superuser:
        raise PermissionDeniedException(required_permissions=["superuser"])
    return current_user