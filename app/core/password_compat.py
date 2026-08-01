"""密码哈希兼容层：支持迁移窗口内的 scrypt 旧哈希（前后端分离迁移）。

前端 TS 实现（src/shared/security/password.ts）：
- scryptSync(password, salt=randomBytes(16), keylen=64)，输出 ``<salt hex>:<hash hex>``
- 默认参数 N=16384 / r=8 / p=1（Node crypto 默认）

策略（懒升级）：
- 验证时按哈希前缀区分：``$2`` 开头 = bcrypt（新），其余 = scrypt（旧）
- 旧哈希验证通过后由调用方以 bcrypt 重哈希并落库（OQ-5 懒升级）
"""

from __future__ import annotations

import hashlib
import secrets

import bcrypt

from app.core.validators import MAX_PASSWORD_BYTES

# 与前端 scrypt 实现对齐
_SCRYPT_KEYLEN = 64
_SCRYPT_SALT_LEN = 16
_SCRYPT_N = 2**14  # 16384
_SCRYPT_R = 8
_SCRYPT_P = 1

_BCRYPT_PREFIX = b"$2"


def is_bcrypt_hash(stored: str) -> bool:
    """判断哈希是否为 bcrypt 格式（$2a/$2b/$2y 开头）。"""
    return stored.startswith("$2")


def verify_password_any(plain_password: str, stored: str) -> bool:
    """验证密码：bcrypt 新格式或 scrypt 旧格式均可。"""
    if is_bcrypt_hash(stored):
        try:
            return bcrypt.checkpw(
                plain_password.encode("utf-8"),
                stored.encode("utf-8"),
            )
        except (ValueError, TypeError):
            # bcrypt 输入超 72 字节等不合法情况一律视为验证失败
            return False
    return _verify_scrypt(plain_password, stored)


def verify_scrypt(plain_password: str, stored: str) -> bool:
    """仅验证 scrypt 旧格式（``saltHex:hashHex``）。"""
    return _verify_scrypt(plain_password, stored)


def needs_rehash(stored: str) -> bool:
    """返回 True 表示需要懒升级（scrypt 旧格式 → bcrypt）。"""
    return not is_bcrypt_hash(stored)


def _verify_scrypt(plain_password: str, stored: str) -> bool:
    """scrypt 兼容校验：salt 16 字节 + 输出 64 字节，恒定时间比较。

    注意：scrypt 无 72 字节限制（与 bcrypt 不同），此处不截断也不拒绝长密码。
    """
    try:
        salt_hex, hash_hex = stored.split(":")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        if len(salt) != _SCRYPT_SALT_LEN or len(expected) != _SCRYPT_KEYLEN:
            return False
        actual = hashlib.scrypt(
            plain_password.encode("utf-8"),
            salt=salt,
            n=_SCRYPT_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
            dklen=_SCRYPT_KEYLEN,
        )
        return secrets.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def hash_scrypt(password: str) -> str:
    """生成 scrypt 旧格式哈希（测试 / 构造旧数据用）。"""
    salt = secrets.token_bytes(_SCRYPT_SALT_LEN)
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password exceeds limit of {MAX_PASSWORD_BYTES} UTF-8 bytes")
    digest = hashlib.scrypt(
        raw,
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_KEYLEN,
    )
    return f"{salt.hex()}:{digest.hex()}"
