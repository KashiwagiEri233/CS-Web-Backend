from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header, Request
from fastapi.security import OAuth2PasswordRequestForm

from app.core.exceptions import (
    InvalidCredentialsException,
    UserNotActiveException,
)
from app.dependencies import get_current_active_user
from app.dependencies_services import get_audit_service, get_auth_service
from app.middleware.rbac import require_permission
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserResponse,
)
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService

router = APIRouter()


def _client_meta(request: Request) -> dict:
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


async def _do_login(auth_service: AuthService, username: str, password: str) -> TokenPair:
    """登录公共逻辑：验证凭据 → 检查激活 → 签发 access + refresh 双 token。"""
    user = await auth_service.authenticate(username, password)

    if not user:
        raise InvalidCredentialsException()

    if not user.is_active:
        raise UserNotActiveException(user_id=user.id)

    return await auth_service.issue_token_pair(user)


@router.post("/login", response_model=TokenPair)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    auth_service: AuthService = Depends(get_auth_service),
) -> Any:
    """用户登录，返回 access + refresh 双 token。"""
    return await _do_login(auth_service, form_data.username, form_data.password)


@router.post("/login-json", response_model=TokenPair)
async def login_json(
    login_data: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> Any:
    """用户登录（JSON 格式），返回 access + refresh 双 token。"""
    return await _do_login(auth_service, login_data.username, login_data.password)


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
    audit: AuditService = Depends(get_audit_service),
    current_user: User = Depends(require_permission("user", "create")),
) -> Any:
    """用户注册（需要 user:create）。查重 + 哈希 + 落库走 AuthService.create_user。"""
    created = await auth_service.create_user(user_data, is_superuser=False)
    meta = _client_meta(request)
    await audit.record(
        action="user.create",
        resource_type="user",
        resource_id=str(created.id),
        actor_id=current_user.id,
        actor_username=current_user.username,
        detail={"username": created.username, "via": "auth.register"},
        **meta,
    )
    return created


@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """获取当前用户信息。"""
    return current_user
