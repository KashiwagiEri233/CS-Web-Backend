"""TOTP secret 加密：HKDF-SHA256 + AES-256-GCM（与前端算法逐字节兼容）。

前端 TS 实现（src/modules/auth/server/totp.ts）：
- 密钥派生：``hkdfSync('sha256', KEY, salt='', info='fztbucs-totp-encryption', 32)``
- 加密：AES-256-GCM，12 字节随机 IV，输出格式 ``<iv hex>:<tag hex>:<cipher hex>``

数据迁移时旧库中的密文可直接用本模块解密（同一主密钥），重加密后落新库。
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

_INFO = b"fztbucs-totp-encryption"
_SALT = b""


def _derive_key() -> bytes:
    """HKDF-SHA256 派生 AES-256 密钥（32 字节），与 Node hkdfSync 语义一致。

    salt 为空字节串：Node 侧传 '' 等价于无 salt（RFC 5869 规定无 salt 时
    使用 HashLen 个零字节，cryptography 的空 salt 行为一致）。
    """
    if not settings.TOTP_ENCRYPTION_KEY:
        raise ValueError("TOTP_ENCRYPTION_KEY must be set from environment variables")
    key_material = settings.TOTP_ENCRYPTION_KEY.encode("utf-8")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        info=_INFO,
    ).derive(key_material)


def encrypt_secret(secret: str) -> str:
    """加密 TOTP secret，返回 ``iv:tag:cipher`` 十六进制串。"""
    key = _derive_key()
    iv = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(iv, secret.encode("utf-8"), None)
    return f"{iv.hex()}:{ciphertext[-16:].hex()}:{ciphertext[:-16].hex()}"


def decrypt_secret(encrypted: str) -> str:
    """解密 ``iv:tag:cipher`` 格式密文；格式或认证失败抛 ValueError。"""
    parts = encrypted.split(":")
    if len(parts) != 3:
        raise ValueError("Invalid encrypted secret format")
    iv_hex, tag_hex, data_hex = parts
    try:
        iv = bytes.fromhex(iv_hex)
        tag = bytes.fromhex(tag_hex)
        data = bytes.fromhex(data_hex)
    except ValueError as exc:
        raise ValueError("Invalid encrypted secret format") from exc
    key = _derive_key()
    try:
        plaintext = AESGCM(key).decrypt(iv, data + tag, None)
    except Exception as exc:  # cryptography.exceptions.InvalidTag 等
        raise ValueError(
            "TOTP secret decryption failed (bad key or tampered data)"
        ) from exc
    return plaintext.decode("utf-8")
