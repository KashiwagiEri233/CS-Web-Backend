"""app/core/validators.py 单元测试。纯函数，不依赖数据库。"""

import pytest

from app.core.validators import (
    validate_password_strength,
    validate_username,
    validate_email,
    validate_sql_like_pattern,
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


class TestValidateEmail:
    def test_valid(self):
        ok, err = validate_email("a.b+x@example.co")
        assert ok and err is None

    @pytest.mark.parametrize("email", ["nope", "a@b", "a@@b.com", "@b.com", "a@b."])
    def test_invalid(self, email):
        ok, err = validate_email(email)
        assert ok is False and err

    def test_too_long(self):
        ok, err = validate_email("a" * 250 + "@example.com")
        assert ok is False and err


class TestValidateSqlLike:
    def test_valid_prefix_suffix(self):
        assert validate_sql_like_pattern("%abc")[0] is True
        assert validate_sql_like_pattern("abc%")[0] is True

    @pytest.mark.parametrize("pat", ["a%b", "ab[c]", "a_b"])
    def test_invalid(self, pat):
        ok, err = validate_sql_like_pattern(pat)
        assert ok is False and err
