from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header, Request
from fastapi.security import OAuth2PasswordRequestForm

from app.core.request_context import get_client_meta
from app.dependencies import get_current_active_user
from app.dependencies_services import get_auth_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter()


@router.post("/login", response_model=TokenPair)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    auth_service: AuthService = Depends(get_auth_service),
) -> Any:
    """用户登录，返回 access + refresh 双 token。"""
    return await auth_service.login(
        form_data.username, form_data.password, get_client_meta(request)
    )


@router.post("/login-json", response_model=TokenPair)
async def login_json(
    request: Request,
    login_data: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> Any:
    """用户登录（JSON 格式），返回 access + refresh 双 token。"""
    return await auth_service.login(
        login_data.username, login_data.password, get_client_meta(request)
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh_token(
    body: RefreshRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> Any:
    """用 refresh token 换取新的 access + refresh（轮换 + 复用检测）。"""
    return await auth_service.refresh_access_token(body.refresh_token)


@router.post("/logout")
async def logout(
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(get_current_active_user),
    authorization: str = Header(default=""),
    body: Optional[RefreshRequest] = Body(None),
) -> Any:
    """登出：撤销可选 refresh + 当前 access 入黑名单。"""
    if body is not None and body.refresh_token:
        await auth_service.revoke_refresh_token(body.refresh_token)

    token = authorization.removeprefix("Bearer ").strip()
    if token:
        await auth_service.blacklist_access_token(token)

    return {"message": "已登出"}


@router.post("/register", response_model=UserResponse)
async def register(
    user_data: UserCreate,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(require_permission("user", "create")),
) -> Any:
    """用户注册（需要 user:create）。创建 + 审计 + 提交走 service 原子入口。"""
    return await auth_service.create_user_with_audit(
        user_data,
        actor=current_user,
        client_meta=get_client_meta(request),
        via="auth.register",
    )


@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """获取当前用户信息。"""
    return current_user
