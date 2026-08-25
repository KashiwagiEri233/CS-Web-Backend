"""app/core/validators.py 单元测试。纯函数，不依赖数据库。"""

import pytest

from app.core.validators import (
    validate_password_strength,
    validate_username,
)


class TestValidatePassword:
    def test_valid(self):
        ok, err = validate_password_strength("Abcd123!")
        assert ok and err is None

    def test_rejects_multibyte_password_over_bcrypt_byte_limit(self):
        ok, err = validate_password_strength("密" * 23 + "Aa1!")
        assert ok is False and err

    @pytest.mark.parametrize(
        "pwd,reason",
        [
            ("Ab1!", "太短"),
            ("A" * 129 + "1!", "太长"),
            ("Abcdefg!", "缺数字"),
            ("1234567!", "缺字母"),
            ("Abcd1234", "缺特殊字符"),
        ],
    )
    def test_invalid(self, pwd, reason):
        ok, err = validate_password_strength(pwd)
        assert ok is False and err  # 返回错误消息


class TestValidateUsername:
    def test_valid(self):
        ok, err = validate_username("alice_01-x")
        assert ok and err is None

    @pytest.mark.parametrize("name", ["ab", "a" * 51, "bad name", "用户名", "a@b"])
    def test_invalid(self, name):
        ok, err = validate_username(name)
        assert ok is False and err
