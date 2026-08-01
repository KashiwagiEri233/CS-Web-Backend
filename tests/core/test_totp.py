"""TOTP 核心算法测试：RFC 6238 测试向量 + Base32 + 备用码格式。"""

import time

from app.core import totp


def test_rfc6238_sha1_vectors():
    """RFC 6238 附录 B：SHA1 / 8 位示例（6 位实现 = 8 位结果 mod 10^6，即后 6 位）。"""
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # "12345678901234567890" 的 Base32
    vectors = {
        59: "94287082",
        1111111109: "07081804",
        1111111111: "14050471",
        1234567890: "89005924",
        2000000000: "69279037",
    }
    for ts, expected8 in vectors.items():
        assert totp.generate_code(secret, ts) == expected8[-6:]


def test_verify_code_window():
    secret = totp.generate_secret()
    now = int(time.time())
    code = totp.generate_code(secret, now)
    assert totp.verify_code(secret, code, now)
    # 前一步的码（窗口内）也应通过
    prev_code = totp.generate_code(secret, now - totp.DEFAULT_PERIOD)
    assert totp.verify_code(secret, prev_code, now)
    # 错误码与两窗口外码应失败
    assert not totp.verify_code(secret, "000000", now)
    far = totp.generate_code(secret, now - 3 * totp.DEFAULT_PERIOD)
    assert not totp.verify_code(secret, far, now)


def test_base32_roundtrip():
    data = b"\x00\x01\x02\x03\x04\x05\x06\x07"
    assert totp.base32_decode(totp.base32_encode(data)) == data
    # 兼容小写与 padding
    encoded = totp.base32_encode(data)
    assert totp.base32_decode(encoded.lower() + "=") == data


def test_generate_secret_format():
    secret = totp.generate_secret()
    # Base32 大写字母 + 数字 2-7
    assert all(c in totp._BASE32_ALPHABET for c in secret)
    assert len(secret) == 32  # 20 字节 → 32 字符


def test_otpauth_uri_format():
    uri = totp.generate_otpauth_uri("user@example.com", "JBSWY3DPEHPK3PXP", "FZTBUCS")
    assert uri.startswith("otpauth://totp/")
    assert "issuer=FZTBUCS" in uri
    assert "secret=JBSWY3DPEHPK3PXP" in uri
    assert "algorithm=SHA1" in uri and "digits=6" in uri and "period=30" in uri
    # label 包含 issuer:email（URL 编码）
    assert "FZTBUCS%3Auser%40example.com" in uri or "FZTBUCS:user@example.com" in uri


def test_backup_codes_format_and_count():
    codes = totp.generate_backup_codes()
    assert len(codes) == 8
    for code in codes:
        assert len(code) == 11
        assert code[5] == "-"
        assert code.replace("-", "").isalnum()
        assert code == code.upper()
