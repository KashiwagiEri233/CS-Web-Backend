"""JWT / 密码安全原语。

支持密钥轮换：签发用当前 SECRET_KEY；校验时依次尝试 SECRET_KEY + JWT_PREVIOUS_SECRET_KEYS。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import List, Optional, Union

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings
from app.core.timezone import now_utc

# bcrypt 最多处理 72 字节密码，超出部分截断（与 bcrypt 算法规范一致）
_BCRYPT_MAX_BYTES = 72


def _truncate_for_bcrypt(password: str) -> bytes:
    """截断超长密码到 bcrypt 的 72 字节上限。"""
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        return raw[:_BCRYPT_MAX_BYTES]
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
            _truncate_for_bcrypt(plain_password),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    """生成密码哈希（bcrypt）。"""
    return bcrypt.hashpw(
        _truncate_for_bcrypt(password),
        bcrypt.gensalt(),
    ).decode("utf-8")


def _signing_key() -> str:
    return settings.SECRET_KEY or ""


def _verification_keys() -> List[str]:
    """校验用密钥列表：当前密钥优先，其后为历史密钥（轮换窗口）。"""
    keys: List[str] = []
    current = settings.SECRET_KEY
    if current:
        keys.append(current)
    prev = getattr(settings, "JWT_PREVIOUS_SECRET_KEYS", "") or ""
    for part in prev.split(","):
        k = part.strip()
        if k and k not in keys:
            keys.append(k)
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
    if expires_delta:
        expire = now_utc() + expires_delta
    else:
        expire = now_utc() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    token_jti = jti or generate_token_jti()
    to_encode.update({"exp": expire, "jti": token_jti})
    encoded_jwt = jwt.encode(
        to_encode, _signing_key(), algorithm=settings.ALGORITHM
    )
    return encoded_jwt, token_jti, expire


def verify_token(token: str) -> Optional[dict]:
    """验证令牌：依次尝试当前密钥与历史密钥（支持轮换窗口）。"""
    algorithms = [settings.ALGORITHM]
    for key in _verification_keys():
        try:
            return jwt.decode(token, key, algorithms=algorithms)
        except JWTError:
            continue
    return None
