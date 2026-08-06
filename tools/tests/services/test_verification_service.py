"""邮箱验证码服务测试：HMAC 哈希、生成与校验流程。"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ErrorCode, ValidationException
from app.services import verification_service
from app.services.verification_service import (
    VerificationService,
    _hash_code,
    _verify_hash_code,
)


def _make_service() -> VerificationService:
    """构造一个 repo 与 commit 全部 mock 的 VerificationService。"""
    db = MagicMock()
    db.commit = AsyncMock()
    svc = VerificationService(db)
    svc.repo = MagicMock()
    svc.repo.invalidate_for_email = AsyncMock()
    svc.repo.create = AsyncMock()
    svc.repo.get_latest_unused = AsyncMock()
    svc.repo.mark_used = AsyncMock()
    return svc


def test_hash_code_produces_consistent_hmac_output():
    with patch.object(verification_service.settings, "SECRET_KEY", "known-secret"):
        h1 = _hash_code("123456")
        h2 = _hash_code("123456")

    assert h1 == h2
    assert isinstance(h1, str)
    # sha256 hexdigest 长度固定为 64
    assert len(h1) == 64
    # 明文不应出现在哈希里
    assert "123456" not in h1


def test_verify_hash_code_returns_true_for_matching_code():
    with patch.object(verification_service.settings, "SECRET_KEY", "known-secret"):
        stored = _hash_code("123456")
        assert _verify_hash_code("123456", stored) is True


def test_verify_hash_code_returns_false_for_wrong_code():
    with patch.object(verification_service.settings, "SECRET_KEY", "known-secret"):
        stored = _hash_code("123456")
        assert _verify_hash_code("000000", stored) is False


def test_verify_hash_code_returns_false_for_mismatched_length():
    with patch.object(verification_service.settings, "SECRET_KEY", "known-secret"):
        # 截断后的哈希长度与实际不符，应在常量时间比较前直接返回 False
        stored = _hash_code("123456")[:32]
        assert _verify_hash_code("123456", stored) is False


async def test_generate_invalidates_old_codes_and_creates_new_record():
    svc = _make_service()
    with (
        patch.object(
            verification_service.settings, "VERIFICATION_CODE_TTL_MINUTES", 10
        ),
        patch(
            "app.services.verification_service.send_verification_code", new=AsyncMock()
        ),
    ):
        await svc.generate("User@Example.com")

    svc.repo.invalidate_for_email.assert_awaited_once_with("user@example.com")
    svc.repo.create.assert_awaited_once()
    args, _ = svc.repo.create.call_args
    assert args[0] == "user@example.com"
    assert isinstance(args[1], str) and len(args[1]) == 64  # code_hash
    assert isinstance(args[2], datetime)  # expires_at
    svc.db.commit.assert_awaited_once()


async def test_generate_returns_6_digit_code_string():
    svc = _make_service()
    with (
        patch.object(
            verification_service.settings, "VERIFICATION_CODE_TTL_MINUTES", 10
        ),
        patch(
            "app.services.verification_service.send_verification_code", new=AsyncMock()
        ),
    ):
        code = await svc.generate("user@example.com")

    assert isinstance(code, str)
    assert len(code) == 6
    assert code.isdigit()
    assert 100000 <= int(code) <= 999999


async def test_generate_calls_send_verification_code():
    svc = _make_service()
    send_mock = AsyncMock()
    with (
        patch.object(
            verification_service.settings, "VERIFICATION_CODE_TTL_MINUTES", 10
        ),
        patch(
            "app.services.verification_service.send_verification_code", new=send_mock
        ),
    ):
        code = await svc.generate("User@Example.com")

    send_mock.assert_awaited_once_with("user@example.com", code)


async def test_verify_returns_false_when_no_record_found():
    svc = _make_service()
    svc.repo.get_latest_unused.return_value = None

    result = await svc.verify("user@example.com", "123456")

    assert result is False
    svc.repo.mark_used.assert_not_awaited()
    svc.db.commit.assert_not_awaited()


async def test_verify_returns_false_when_hash_does_not_match():
    svc = _make_service()
    with patch.object(verification_service.settings, "SECRET_KEY", "known-secret"):
        record = MagicMock()
        record.id = 1
        record.code_hash = _hash_code("999999")
        svc.repo.get_latest_unused.return_value = record

        result = await svc.verify("user@example.com", "123456")

    assert result is False
    svc.repo.mark_used.assert_not_awaited()
    svc.db.commit.assert_not_awaited()


async def test_verify_returns_true_and_marks_used_on_success():
    svc = _make_service()
    with patch.object(verification_service.settings, "SECRET_KEY", "known-secret"):
        stored = _hash_code("123456")
        record = MagicMock()
        record.id = 42
        record.code_hash = stored
        svc.repo.get_latest_unused.return_value = record

        result = await svc.verify("User@Example.com", "123456")

    assert result is True
    svc.repo.get_latest_unused.assert_awaited_once()
    # 邮箱应被归一化为小写
    call_args, _ = svc.repo.get_latest_unused.call_args
    assert call_args[0] == "user@example.com"
    svc.repo.mark_used.assert_awaited_once_with(42)
    svc.db.commit.assert_awaited_once()


async def test_verify_or_raise_raises_validation_exception_on_failure():
    svc = _make_service()
    svc.repo.get_latest_unused.return_value = None

    with pytest.raises(ValidationException) as exc_info:
        await svc.verify_or_raise("user@example.com", "123456")

    assert exc_info.value.error_code == ErrorCode.Validation.VERIFICATION_CODE_INVALID


async def test_verify_or_raise_does_not_raise_on_success():
    svc = _make_service()
    with patch.object(verification_service.settings, "SECRET_KEY", "known-secret"):
        stored = _hash_code("123456")
        record = MagicMock()
        record.id = 42
        record.code_hash = stored
        svc.repo.get_latest_unused.return_value = record

        # 成功时不应抛出异常
        await svc.verify_or_raise("user@example.com", "123456")

    svc.repo.mark_used.assert_awaited_once_with(42)
