"""RFC 6238 TOTP 实现（与前端自实现算法逐字节兼容）。

前端 TS 实现（src/modules/auth/server/totp.ts）：
- SHA1 / 6 位数字 / 30 秒步长 / ±1 窗口 / secret 160-bit 随机 → Base32（RFC 4648）
本模块保持相同语义，使迁移窗口内新旧两端可互相验证。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from urllib.parse import quote

# 默认参数与前端一致
DEFAULT_DIGITS = 6
DEFAULT_ALGORITHM = "SHA1"
DEFAULT_PERIOD = 30  # 秒
SECRET_BYTES = 20  # 160 bits
BACKUP_CODE_COUNT = 8

_BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def base32_encode(data: bytes) -> str:
    """RFC 4648 Base32（无 padding，大写）。"""
    return base64.b32encode(data).decode("ascii").rstrip("=")


def base32_decode(encoded: str) -> bytes:
    """RFC 4648 Base32 解码（容忍小写与多余 padding）。"""
    cleaned = encoded.replace("=", "").upper()
    # b32decode 需要 8 的倍数长度，补足 padding
    pad = (-len(cleaned)) % 8
    return base64.b32decode(cleaned + "=" * pad)


def generate_secret() -> str:
    """生成 160-bit 随机 TOTP secret（Base32 编码）。"""
    return base32_encode(secrets.token_bytes(SECRET_BYTES))


def generate_otpauth_uri(email: str, secret: str, issuer: str) -> str:
    """生成 otpauth:// URI（二维码 / 手动录入）。label 为 ``{issuer}:{email}``。"""
    label = quote(f"{issuer}:{email}", safe="")
    params = {
        "secret": secret,
        "issuer": issuer,
        "algorithm": DEFAULT_ALGORITHM,
        "digits": str(DEFAULT_DIGITS),
        "period": str(DEFAULT_PERIOD),
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"otpauth://totp/{label}?{query}"


def _hotp_code(secret: bytes, counter: int, digits: int = DEFAULT_DIGITS) -> str:
    """HOTP 动态截断（RFC 4226）：返回固定位数字符串。"""
    msg = counter.to_bytes(8, "big")
    digest = hmac.new(secret, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = (
        ((digest[offset] & 0x7F) << 24)
        | (digest[offset + 1] << 16)
        | (digest[offset + 2] << 8)
        | digest[offset + 3]
    )
    return f"{binary % (10 ** digits):0{digits}d}"


def generate_code(secret: str, timestamp: int, period: int = DEFAULT_PERIOD) -> str:
    """生成给定时刻（Unix 秒）的 TOTP 码。"""
    counter = timestamp // period
    return _hotp_code(base32_decode(secret), counter)


def verify_code(
    secret: str,
    code: str,
    timestamp: int,
    *,
    period: int = DEFAULT_PERIOD,
    window_steps: int = 1,
) -> bool:
    """验证 TOTP 码（允许 ±window_steps 个时间步的时钟偏移）。

    使用 hmac.compare_digest 恒定时间比较。
    """
    if not code.isdigit() or len(code) != DEFAULT_DIGITS:
        return False
    for offset in range(-window_steps, window_steps + 1):
        expected = generate_code(secret, timestamp + offset * period, period)
        if hmac.compare_digest(code, expected):
            return True
    return False


def generate_backup_codes(count: int = BACKUP_CODE_COUNT) -> list[str]:
    """生成一次性备用码：10 位大写十六进制，格式 ``XXXXX-XXXXX``。"""
    codes: list[str] = []
    for _ in range(count):
        raw = secrets.token_hex(5).upper()
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes
