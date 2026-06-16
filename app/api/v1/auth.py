from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    InvalidCredentialsException,
    UserNotActiveException,
    UserAlreadyExistsException,
    PermissionDeniedException,
)
from app.database import get_db
from app.dependencies import get_current_active_user, get_current_superuser
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.auth import Token, LoginRequest, UserResponse, UserCreate
from app.services.auth_service import AuthService

router = APIRouter()


async def _do_login(auth_service: AuthService, username: str, password: str):
    """登录公共逻辑：验证凭据 → 检查激活 → 生成令牌"""
    user = await auth_service.authenticate(username, password)

    if not user:
        raise InvalidCredentialsException()

    if not user.is_active:
        raise UserNotActiveException(user_id=user.id)

    return await auth_service.create_token_for_user(user)


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """用户登录，返回访问令牌"""
    auth_service = AuthService(db)
    return await _do_login(auth_service, form_data.username, form_data.password)


@router.post("/login-json", response_model=Token)
async def login_json(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """用户登录（JSON格式），返回访问令牌"""
    auth_service = AuthService(db)
    return await _do_login(auth_service, login_data.username, login_data.password)


@router.post("/register", response_model=UserResponse)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
) -> Any:
    """
    用户注册（需要超级用户权限）
    使用 Pydantic body 接收，UserCreate 已包含密码强度/用户名/邮箱验证
    """
    user_repo = UserRepository(db)

    # 检查用户名是否已存在
    existing_user = await user_repo.get_by_username(user_data.username)
    if existing_user:
        raise UserAlreadyExistsException(username=user_data.username)

    # 检查邮箱是否已存在
    existing_email = await user_repo.get_by_email(user_data.email)
    if existing_email:
        raise UserAlreadyExistsException(email=user_data.email)

    # 创建新用户
    from app.core.security import get_password_hash

    user_dict = {
        "username": user_data.username,
        "email": user_data.email,
        "hashed_password": get_password_hash(user_data.password),
        "full_name": user_data.full_name,
        "is_active": user_data.is_active,
        "is_superuser": False,
    }

    created_user = await user_repo.create(user_dict)
    return created_user


@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """
    获取当前用户信息
    """
    return current_user


@router.post("/refresh", response_model=Token)
async def refresh_token(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    刷新访问令牌
    """
    auth_service = AuthService(db)
    return await auth_service.create_token_for_user(current_user)