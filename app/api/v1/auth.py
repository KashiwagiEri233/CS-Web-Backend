from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InvalidCredentialsException,
    UserNotActiveException,
)
from app.database import get_db
from app.dependencies import get_current_active_user, get_current_superuser
from app.models.user import User
from app.schemas.auth import (
    TokenPair,
    RefreshRequest,
    LoginRequest,
    UserResponse,
    UserCreate,
)
from app.services.auth_service import AuthService

router = APIRouter()


async def _do_login(auth_service: AuthService, username: str, password: str) -> TokenPair:
    """登录公共逻辑：验证凭据 → 检查激活 → 签发 access + refresh 双 token"""
    user = await auth_service.authenticate(username, password)

    if not user:
        raise InvalidCredentialsException()

    if not user.is_active:
        raise UserNotActiveException(user_id=user.id)

    return await auth_service.issue_token_pair(user)


@router.post("/login", response_model=TokenPair)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """用户登录，返回 access + refresh 双 token"""
    auth_service = AuthService(db)
    return await _do_login(auth_service, form_data.username, form_data.password)


@router.post("/login-json", response_model=TokenPair)
async def login_json(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """用户登录（JSON格式），返回 access + refresh 双 token"""
    auth_service = AuthService(db)
    return await _do_login(auth_service, login_data.username, login_data.password)


@router.post("/refresh", response_model=TokenPair)
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """用 refresh token 换取新的 access + refresh（轮换 + 复用检测）"""
    auth_service = AuthService(db)
    return await auth_service.refresh_access_token(body.refresh_token)


@router.post("/logout")
async def logout(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    authorization: str = Header(default=""),
    body: RefreshRequest = None,
) -> Any:
    """登出：撤销 refresh token（如提供）+ 当前 access token 加入黑名单。

    access token 从 Authorization 头解析；refresh token 从 body（可选）。
    """
    auth_service = AuthService(db)

    # 撤销 refresh token（如提供）
    if body is not None and body.refresh_token:
        await auth_service.revoke_refresh_token(body.refresh_token)

    # 当前 access token 入黑名单
    token = authorization.removeprefix("Bearer ").strip()
    if token:
        await auth_service.blacklist_access_token(token)

    return {"message": "已登出"}


@router.post("/register", response_model=UserResponse)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
) -> Any:
    """
    用户注册（需要超级用户权限）
    使用 Pydantic body 接收，UserCreate 已包含密码强度/用户名/邮箱验证。
    查重 + 哈希 + 落库统一走 AuthService.create_user。
    """
    auth_service = AuthService(db)
    return await auth_service.create_user(user_data, is_superuser=False)


@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """获取当前用户信息"""
    return current_user