import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

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
    """refresh token 哈希：存库用 sha256（固定 64 位十六进制）。

    用 sha256 而非 bcrypt：refresh token 足够长且高熵，bcrypt 是为了抵抗低熵密码的离线穷举。
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码（bcrypt）。"""
    try:
        return bcrypt.checkpw(
            _truncate_for_bcrypt(plain_password),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        # 哈希格式不合法（旧数据/损坏），返回 False 而非抛异常
        return False


def get_password_hash(password: str) -> str:
    """生成密码哈希（bcrypt）。"""
    return bcrypt.hashpw(
        _truncate_for_bcrypt(password),
        bcrypt.gensalt(),
    ).decode("utf-8")


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    jti: Optional[str] = None,
) -> tuple[str, str, datetime]:
    """创建访问令牌。

    返回 (token, jti, expire)：
    - jti 用于黑名单；调用方可在签发后据此建立黑名单映射。
    - data 里的 "sub" 等声明仍由调用方提供。
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    token_jti = jti or generate_token_jti()
    to_encode.update({"exp": expire, "jti": token_jti})
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt, token_jti, expire


def verify_token(token: str) -> Optional[dict]:
    """验证令牌"""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        return None
