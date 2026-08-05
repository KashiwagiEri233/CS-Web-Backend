"""TOTP secret 加密测试：往返 + 与前端（Node HKDF+AES-256-GCM）算法交叉验证。"""

import pytest

from app.core import totp_encryption
from app.core.config import settings


def test_encrypt_decrypt_roundtrip():
    secret = "JBSWY3DPEHPK3PXP"
    encrypted = totp_encryption.encrypt_secret(secret)
    assert ":" in encrypted
    parts = encrypted.split(":")
    assert len(parts) == 3  # iv:tag:cipher
    assert totp_encryption.decrypt_secret(encrypted) == secret


def test_tampered_ciphertext_raises():
    encrypted = totp_encryption.encrypt_secret("SECRET123")
    iv, tag, cipher = encrypted.split(":")
    # 篡改密文最后一位 → GCM 认证失败
    flipped = cipher[:-1] + ("0" if cipher[-1] != "0" else "1")
    with pytest.raises(ValueError):
        totp_encryption.decrypt_secret(f"{iv}:{tag}:{flipped}")


def test_invalid_format_raises():
    with pytest.raises(ValueError):
        totp_encryption.decrypt_secret("not-a-valid-format")
    with pytest.raises(ValueError):
        totp_encryption.decrypt_secret("aa:bb")


def test_cross_implementation_vector():
    """与前端 Node 实现产出的参考向量交叉验证（同一主密钥下可互相解密）。

    参考向量由 Node 生成（salt='' / info='fztbucs-totp-encryption'）：
      key = hkdfSync('sha256', KEY_MATERIAL, '', 'fztbucs-totp-encryption', 32)
      iv = e0e848bf8ea10b03769f0fe9, tag = 189ff1a9244ca7e4d1b9f7715142b3b3
      cipher = 03d914c93280b882cbc416e7cbafb014（明文 JBSWY3DPEHPK3PXP）
    """
    monkeypatch_key = "test-totp-encryption-key-at-least-32-bytes"
    if settings.TOTP_ENCRYPTION_KEY != monkeypatch_key:
        pytest.skip("需要测试密钥 test-totp-encryption-key-at-least-32-bytes")
    encrypted = (
        "e0e848bf8ea10b03769f0fe9:189ff1a9244ca7e4d1b9f7715142b3b3:"
        "03d914c93280b882cbc416e7cbafb014"
    )
    assert totp_encryption.decrypt_secret(encrypted) == "JBSWY3DPEHPK3PXP"
