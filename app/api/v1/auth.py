from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm

from app.core.exceptions import (
    ConflictException,
    ErrorCode,
    NotFoundException,
    ValidationException,
)
from app.core.request_context import get_client_meta
from app.dependencies import get_current_active_user, get_optional_current_user
from app.dependencies_services import get_auth_service, get_verification_service
from app.models.user import User
from app.schemas.auth import (
    EmailLoginRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    SendCodeRequest,
    SessionListResponse,
    TokenPair,
    TwoFactorCodeRequest,
    TwoFactorSetupResponse,
    TwoFactorStatusResponse,
    TwoFactorVerifyRequest,
)
from app.services.auth_service import AuthService
from app.services.oauth_service import oauth_service
from app.services.password_reset_service import PasswordResetService
from app.services.verification_service import VerificationService

router = APIRouter()


@router.post("/login", response_model=TokenPair)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    auth_service: AuthService = Depends(get_auth_service),
) -> Any:
    """用户登录（OAuth2 表单，用户名），返回 access + refresh 双 token。"""
    return await auth_service.login(
        form_data.username, form_data.password, get_client_meta(request)
    )


@router.post("/login-json", response_model=TokenPair)
async def login_json(
    request: Request,
    login_data: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> Any:
    """用户登录（JSON，用户名），返回 access + refresh 双 token。"""
    return await auth_service.login(
        login_data.username, login_data.password, get_client_meta(request)
    )


@router.post("/login-email", response_model=LoginResponse)
async def login_email(
    request: Request,
    login_data: EmailLoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> Any:
    """邮箱登录（前端主路径）：2FA 未启用直接返回双 token；已启用返回预认证 token。"""
    result = await auth_service.login_by_email(
        login_data.email, login_data.password, get_client_meta(request)
    )
    return _to_login_response(result)


@router.post("/register", response_model=LoginResponse)
async def register(
    request: Request,
    user_data: RegisterRequest,
    verification: VerificationService = Depends(get_verification_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> Any:
    """公开注册（邮箱 + 密码 + 验证码），创建用户并自动登录。

    原脚手架「管理员建号」（user:create）接口移至 Phase 2 管理端。
    """
    await verification.verify_or_raise(user_data.email, user_data.code)
    pair = await auth_service.register(
        user_data.email, user_data.password, get_client_meta(request)
    )
    return _to_login_response(
        {"requires_2fa": False, "two_factor_token": None, "pair": pair}
    )


@router.post("/send-code")
async def send_code(
    request: Request,
    body: SendCodeRequest,
    verification: VerificationService = Depends(get_verification_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> Any:
    """发送邮箱验证码（注册用）；已注册邮箱返回 409。"""
    if await auth_service.user_repo.get_by_email(body.email.lower()):
        raise ConflictException(
            message="该邮箱已注册，请直接登录或使用忘记密码功能",
            error_code=ErrorCode.User.EMAIL_EXISTS,
        )
    await verification.generate(body.email)
    return {"ok": True, "message": "验证码已发送"}


@router.post("/forgot-password")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> Any:
    """忘记密码：创建重置申请等待管理员审批。防枚举：无论邮箱是否注册都返回相同消息。"""
    reset_service = PasswordResetService(auth_service.db, audit=auth_service.audit)
    await reset_service.create_request(body.email)
    return {
        "ok": True,
        "message": "如该邮箱已注册，您的申请已提交，请等待管理员处理",
    }


@router.get("/me", response_model=MeResponse)
async def read_users_me(
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """获取当前用户信息（用户 + 角色 + 2FA 状态）。"""
    return await auth_service.get_me(current_user.id)


# ------------------------------------------------------------------ 2FA


@router.get("/2fa", response_model=TwoFactorStatusResponse)
async def two_factor_status(
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """查询当前用户 2FA 状态（是否已设置 / 是否已启用）。"""
    return {
        "enabled": await auth_service.totp_service.is_enabled(current_user.id),
        "setup": await auth_service.totp_service.is_setup(current_user.id),
    }


@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
async def two_factor_setup(
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """初始化 2FA：生成 secret + otpauth URI + 备用码（未启用，待 confirm）。"""
    return await auth_service.totp_service.setup(current_user.id, current_user.email)


@router.post("/2fa/verify", response_model=LoginResponse)
async def two_factor_verify(
    request: Request,
    body: TwoFactorVerifyRequest,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: Optional[User] = Depends(get_optional_current_user),
) -> Any:
    """2FA 验证码：设置确认（mode=setup，需登录）或登录二次验证（mode=login）。"""
    if body.mode == "setup":
        if current_user is None:
            raise ValidationException(
                message="未登录", error_code=ErrorCode.Auth.AUTHENTICATION_FAILED
            )
        await auth_service.totp_service.confirm(current_user.id, body.code)
        return {"ok": True}

    if not body.two_factor_token:
        raise ValidationException(
            message="缺少认证 token", error_code=ErrorCode.Validation.VALIDATION_FAILED
        )
    pair = await auth_service.complete_two_factor_login(
        body.two_factor_token, body.code, get_client_meta(request)
    )
    return _to_login_response(
        {"requires_2fa": False, "two_factor_token": None, "pair": pair}
    )


@router.post("/2fa/disable")
async def two_factor_disable(
    body: TwoFactorCodeRequest,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """禁用 2FA（需当前 TOTP/备用码）。"""
    await auth_service.totp_service.disable(current_user.id, body.code)
    return {"ok": True}


@router.post("/2fa/backup-codes")
async def two_factor_backup_codes(
    body: TwoFactorCodeRequest,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """重新生成备用码（需当前 TOTP/备用码）。"""
    codes = await auth_service.totp_service.regenerate_backup_codes(
        current_user.id, body.code
    )
    return {"backupCodes": codes}


# ------------------------------------------------------------------ OAuth


@router.get("/oauth/github")
async def oauth_github_entry() -> Any:
    """GitHub OAuth 入口：302 跳转 GitHub 授权页；未配置返回 400。"""
    url = oauth_service.authorization_url()
    if url is None:
        raise ValidationException(
            message="GitHub OAuth 未配置",
            error_code=ErrorCode.Auth.OAUTH_NOT_CONFIGURED,
        )
    return RedirectResponse(url, status_code=302)


@router.get("/oauth/github/callback", response_model=LoginResponse)
async def oauth_github_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    auth_service: AuthService = Depends(get_auth_service),
) -> Any:
    """GitHub OAuth 回调：校验 state → 换 token → 登录/注册 → 返回登录结果。"""
    info = await oauth_service.verify_callback(code, state)
    result = await auth_service.login_with_github(info, get_client_meta(request))
    return _to_login_response(result)


# ------------------------------------------------------------------ 会话管理


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """设备列表：活跃 refresh token（含 ip/user_agent）。"""
    sessions = await auth_service.list_sessions(current_user.id)
    return SessionListResponse(sessions=sessions)


@router.delete("/sessions/{token_id}")
async def delete_session(
    token_id: int,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """远程登出：撤销指定 refresh token（须属于当前用户）。"""
    revoked = await auth_service.revoke_session(current_user.id, token_id)
    if not revoked:
        raise NotFoundException(
            message="会话不存在或已失效",
            resource_type="session",
            resource_id=str(token_id),
        )
    return {"ok": True}


@router.delete("/sessions/all")
async def revoke_all_sessions(
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """一键登出全部设备：撤销当前用户所有 refresh token（含当前设备）。"""
    revoked = await auth_service.revoke_all_user_tokens(current_user.id)
    return {"ok": True, "revoked": revoked}


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


def _to_login_response(result: dict) -> dict:
    """把 service 登录结果映射为 LoginResponse（pair 或 2FA 预认证）。"""
    if result.get("requires_2fa"):
        return {
            "requires_2fa": True,
            "two_factor_token": result.get("two_factor_token"),
            "access_token": None,
            "refresh_token": None,
            "token_type": None,
            "expires_in": None,
        }
    pair = result.get("pair")
    if pair is None:  # 防御：requires_2fa 与 pair 同时缺失属编程错误
        raise ValidationException(
            message="登录状态异常", error_code=ErrorCode.Auth.AUTHENTICATION_FAILED
        )
    return {
        "requires_2fa": False,
        "two_factor_token": None,
        "access_token": pair.access_token,
        "refresh_token": pair.refresh_token,
        "token_type": pair.token_type,
        "expires_in": pair.expires_in,
    }
