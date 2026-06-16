import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    # bcrypt有72字节的限制，所以需要截断长密码
    if len(plain_password.encode("utf-8")) > 72:
        plain_password = plain_password.encode("utf-8")[:72].decode(
            "utf-8", errors="ignore"
        )
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    # bcrypt有72字节的限制，所以需要截断长密码
    if len(password.encode("utf-8")) > 72:
        password = password.encode("utf-8")[:72].decode("utf-8", errors="ignore")
    return pwd_context.hash(password)


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
