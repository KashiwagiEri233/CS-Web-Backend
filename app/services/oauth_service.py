"""GitHub OAuth 登录服务：httpx 异步实现，state 防 CSRF。

与前端语义对齐（src/modules/auth/server/oauth.ts）：
- state 一次性（校验后即删）、10 分钟过期
- 邮箱已注册但未绑 GitHub 时不自动绑定（防账号接管）→ GITHUB_EMAIL_CONFLICT
- 新用户创建时随机密码（用户后续走「忘记密码」或手动改密）
"""

from __future__ import annotations

import secrets
import time
from typing import Optional

import httpx

from app.core.config import settings
from app.core.exceptions import ErrorCode, ValidationException
from app.core.loguru_logger import get_logger

logger = get_logger("oauth")

_STATE_TTL_SECONDS = 10 * 60
_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_API_BASE = "https://api.github.com"


class OAuthService:
    """GitHub OAuth。state 存内存 Map（进程内；多实例时各实例独立校验）。

    多实例部署时如需跨实例一致性，可把 state 迁到 Redis；当前规模下单进程足够。
    """

    def __init__(self) -> None:
        self._states: dict[str, float] = {}

    # ------------------------------------------------------------------ state

    def generate_state(self) -> str:
        """生成一次性 state 并登记过期时间。"""
        state = secrets.token_hex(32)
        self._states[state] = time.time() + _STATE_TTL_SECONDS
        return state

    def verify_state(self, state: str) -> None:
        """校验 state：必须存在且未过期；校验后立即删除（一次性）。"""
        expires_at = self._states.pop(state, None)
        if expires_at is None:
            raise ValidationException(
                message="OAuth state 无效",
                error_code=ErrorCode.Auth.OAUTH_STATE_INVALID,
            )
        if time.time() > expires_at:
            raise ValidationException(
                message="OAuth state 已过期",
                error_code=ErrorCode.Auth.OAUTH_STATE_EXPIRED,
            )

    # ------------------------------------------------------------------ 流程

    @property
    def configured(self) -> bool:
        return bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET)

    def authorization_url(self) -> Optional[str]:
        """构造 GitHub 授权 URL；未配置时返回 None。"""
        if not self.configured:
            return None
        params = {
            "client_id": settings.GITHUB_CLIENT_ID,
            "redirect_uri": self._callback_url(),
            "scope": "user:email",
            "state": self.generate_state(),
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{_GITHUB_AUTHORIZE_URL}?{query}"

    async def exchange_code(self, code: str) -> str:
        """用 code 换取 GitHub access_token。"""
        if not self.configured:
            raise ValidationException(
                message="OAuth 未配置", error_code=ErrorCode.Auth.OAUTH_NOT_CONFIGURED
            )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _GITHUB_TOKEN_URL,
                data={
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": self._callback_url(),
                },
                headers={"Accept": "application/json"},
            )
        if resp.status_code != 200:
            logger.warning("github token exchange failed: status={}", resp.status_code)
            raise ValidationException(
                message="GitHub OAuth 失败", error_code=ErrorCode.Auth.OAUTH_ERROR
            )
        data = resp.json()
        access_token = data.get("access_token")
        if not access_token or data.get("error"):
            logger.warning(
                "github token exchange error: {}", data.get("error_description")
            )
            raise ValidationException(
                message="GitHub OAuth 失败", error_code=ErrorCode.Auth.OAUTH_ERROR
            )
        return access_token

    async def _fetch_user(self, access_token: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_GITHUB_API_BASE}/user",
                headers={
                    "Authorization": f"token {access_token}",
                    "User-Agent": "fztbucs-oauth",
                },
            )
            if resp.status_code != 200:
                raise ValidationException(
                    message="GitHub OAuth 失败", error_code=ErrorCode.Auth.OAUTH_ERROR
                )
            return resp.json()

    async def _fetch_primary_email(self, access_token: str) -> str:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_GITHUB_API_BASE}/user/emails",
                headers={
                    "Authorization": f"token {access_token}",
                    "User-Agent": "fztbucs-oauth",
                },
            )
            if resp.status_code != 200:
                raise ValidationException(
                    message="GitHub OAuth 失败", error_code=ErrorCode.Auth.OAUTH_ERROR
                )
            emails = resp.json()
        primary_verified = next(
            (e for e in emails if e.get("primary") and e.get("verified")), None
        )
        if primary_verified:
            return primary_verified["email"]
        any_verified = next((e for e in emails if e.get("verified")), None)
        if any_verified:
            return any_verified["email"]
        raise ValidationException(
            message="GitHub OAuth 失败", error_code=ErrorCode.Auth.OAUTH_ERROR
        )

    async def verify_callback(self, code: str, state: str) -> dict:
        """完成 OAuth 回调：返回 {github_id, email, login, name, avatar_url, html_url}。"""
        self.verify_state(state)
        access_token = await self.exchange_code(code)
        user = await self._fetch_user(access_token)
        email = await self._fetch_primary_email(access_token)
        return {
            "github_id": str(user.get("id", "")),
            "email": email.lower(),
            "login": user.get("login", ""),
            "name": user.get("name") or user.get("login", ""),
            "avatar_url": user.get("avatar_url") or "",
            "html_url": user.get("html_url") or "",
        }

    def _callback_url(self) -> str:
        if settings.GITHUB_CALLBACK_URL:
            return settings.GITHUB_CALLBACK_URL
        return f"{settings.SITE_URL.rstrip('/')}/api/auth/oauth/github/callback"


# 模块级单例（无状态除内存 state；跨请求共享以支持 state 校验）
oauth_service = OAuthService()
