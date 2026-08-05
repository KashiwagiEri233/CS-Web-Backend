"""密码哈希兼容层测试：scrypt 旧格式（Node 生成参考向量）+ bcrypt 新格式 + 懒升级判定。"""

from app.core.password_compat import (
    hash_scrypt,
    is_bcrypt_hash,
    needs_rehash,
    verify_password_any,
    verify_scrypt,
)
from app.core.security import get_password_hash

# Node crypto.scryptSync 生成的真实前端哈希（salt 16B + 输出 64B，N=16384/r=8/p=1）：
#   salt = 8754f42a127b4637cad03c3823c6956f
#   hash(scryptSync('MigrateMe2026!', salt, 64))
NODE_SCRYPT_HASH = (
    "8754f42a127b4637cad03c3823c6956f:"
    "26e27c207873dd6f0cd79e9e539e0c36d7285e3fa1af26c73a12ccf9e85f7539"
    "2a4dd5af4fdc1b9449162e6149eaa45ac12e9ab9758f6f0aa936ce11652c2eec"
)


def test_verify_node_scrypt_hash():
    """前端 scrypt 哈希可被后端验证（迁移窗口核心能力）。"""
    assert verify_scrypt("MigrateMe2026!", NODE_SCRYPT_HASH)
    assert not verify_scrypt("wrong-password", NODE_SCRYPT_HASH)


def test_verify_password_any_both_formats():
    assert verify_password_any("MigrateMe2026!", NODE_SCRYPT_HASH)
    bcrypt_hash = get_password_hash("SecurePass123!")
    assert verify_password_any("SecurePass123!", bcrypt_hash)
    assert not verify_password_any("nope", bcrypt_hash)


def test_needs_rehash_detection():
    assert needs_rehash(NODE_SCRYPT_HASH)
    assert not needs_rehash(get_password_hash("SecurePass123!"))


def test_is_bcrypt_hash():
    assert is_bcrypt_hash("$2b$12$abcdefghijklmnopqrstuv")
    assert not is_bcrypt_hash(NODE_SCRYPT_HASH)


def test_hash_scrypt_roundtrip():
    """自产 scrypt 哈希（构造旧数据用）可验证。"""
    stored = hash_scrypt("legacy-password")
    assert verify_scrypt("legacy-password", stored)
    assert not verify_scrypt("other", stored)


def test_malformed_stored_hash():
    assert not verify_scrypt("x", "not-a-hash")
    assert not verify_scrypt("x", "abc:def:ghi")
    assert not verify_scrypt("x", "abc")  # 无冒号
    assert not verify_password_any("x", "$2b$12$short")  # bcrypt 长度不足
