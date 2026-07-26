"""JWT / 密码安全原语。

支持密钥轮换：签发用当前 SECRET_KEY；校验时依次尝试 SECRET_KEY + JWT_PREVIOUS_SECRET_KEYS。
"""

from __future__ import annotations

import hashlib
import secrets
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional

import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError

from app.core.config import settings
from app.core.timezone import now_utc
from app.core.validators import MAX_PASSWORD_BYTES


def _password_bytes(password: str) -> bytes:
    """编码 bcrypt 密码，并拒绝会发生静默截断的输入。"""
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"password exceeds bcrypt limit of {MAX_PASSWORD_BYTES} UTF-8 bytes"
        )
    return raw


def generate_token_jti() -> str:
    """生成 access token 的唯一标识（JWT id），用于黑名单。"""
    return secrets.token_urlsafe(16)


def generate_refresh_token() -> str:
    """生成 refresh token 明文（URL 安全，足够长以抗穷举）。"""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """refresh token 哈希：存库用 sha256（固定 64 位十六进制）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码（bcrypt）。"""
    try:
        return bcrypt.checkpw(
            _password_bytes(plain_password),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    """生成密码哈希（bcrypt）。"""
    return bcrypt.hashpw(
        _password_bytes(password),
        bcrypt.gensalt(),
    ).decode("utf-8")


async def async_verify_password(plain_password: str, hashed_password: str) -> bool:
    """在线程池执行 bcrypt 校验，避免阻塞 FastAPI 事件循环。"""
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)


async def async_get_password_hash(password: str) -> str:
    """在线程池执行 bcrypt 哈希，避免阻塞 FastAPI 事件循环。"""
    return await asyncio.to_thread(get_password_hash, password)


def _signing_key() -> str:
    return settings.SECRET_KEY or ""


# 解析后的校验密钥缓存。键为 (当前密钥, 历史密钥原串)，配置变化（测试里 monkeypatch
# settings）会自然失效；避免每次校验 token 都重新 split 一遍配置字符串——鉴权是热路径。
_VERIFICATION_KEYS_CACHE: dict[tuple[str, str], List[str]] = {}


def _verification_keys() -> List[str]:
    """校验用密钥列表：当前密钥优先，其后为历史密钥（轮换窗口）。"""
    current = settings.SECRET_KEY or ""
    prev = getattr(settings, "JWT_PREVIOUS_SECRET_KEYS", "") or ""

    cached = _VERIFICATION_KEYS_CACHE.get((current, prev))
    if cached is not None:
        return cached

    keys: List[str] = []
    if current:
        keys.append(current)
    for part in prev.split(","):
        k = part.strip()
        if k and k not in keys:
            keys.append(k)

    # 密钥组合是有限集合（当前 + 一次轮换窗口），不会无界增长
    _VERIFICATION_KEYS_CACHE[(current, prev)] = keys
    return keys


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    jti: Optional[str] = None,
) -> tuple[str, str, datetime]:
    """创建访问令牌。

    返回 (token, jti, expire)。
    """
    to_encode = data.copy()
    issued_at = now_utc()
    if expires_delta:
        expire = issued_at + expires_delta
    else:
        expire = issued_at + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    token_jti = jti or generate_token_jti()
    to_encode.update(
        {
            "exp": expire,
            "iat": issued_at,
            "jti": token_jti,
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
            "token_type": "access",
        }
    )
    encoded_jwt = jwt.encode(to_encode, _signing_key(), algorithm=settings.ALGORITHM)
    return encoded_jwt, token_jti, expire


def verify_token(token: str) -> Optional[dict]:
    """验证 access token 的签名、签发方、受众和类型，并强制要求 exp 声明。

    ``JWT_ACCEPT_LEGACY_TOKENS`` 仅用于短期迁移：只接受完全不含新增声明的旧 token，
    不会把 issuer/audience 错误的新 token 降级成 legacy 放行。
    """
    algorithms = [settings.ALGORITHM]
    for key in _verification_keys():
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=algorithms,
                issuer=settings.JWT_ISSUER,
                audience=settings.JWT_AUDIENCE,
                # 强制 exp：PyJWT 默认只在 exp 存在时才校验过期，缺失则永不过期。
                options={"require": ["exp"]},
            )
            if payload.get("token_type") != "access":
                continue
            return payload
        except InvalidTokenError:
            continue

    if settings.JWT_ACCEPT_LEGACY_TOKENS:
        for key in _verification_keys():
            try:
                payload = jwt.decode(
                    token,
                    key,
                    algorithms=algorithms,
                    options={
                        "verify_iss": False,
                        "verify_aud": False,
                        "require": ["exp"],
                    },
                )
            except InvalidTokenError:
                continue
            if any(claim in payload for claim in ("iss", "aud", "token_type")):
                continue
            return payload
    return None
