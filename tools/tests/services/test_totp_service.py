"""TOTPService 单元测试（不依赖真实数据库 / 加密 / bcrypt）。

覆盖 is_enabled / is_setup / setup / confirm / verify / disable / regenerate。
repo、totp_core、totp_encryption、bcrypt 哈希函数均以 mock 替换。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ErrorCode, ValidationException
from app.services.totp_service import TOTPService


def _make_service(monkeypatch) -> TOTPService:
    """构造 repo 与外部依赖均被 mock 的 TOTPService。

    - TwoFactorAuthRepository → AsyncMock（self.repo 直接可配置）
    - totp_core / totp_encryption → MagicMock（默认 verify_code=False）
    - async_get_password_hash → ``hash:<code>``；async_verify_password → False
    """
    repo = AsyncMock()
    monkeypatch.setattr(
        "app.services.totp_service.TwoFactorAuthRepository",
        lambda db: repo,
    )

    totp_core = MagicMock()
    totp_core.generate_secret.return_value = "JBSWY3DPEHPK3PXP"
    totp_core.generate_otpauth_uri.return_value = "otpauth://totp/test"
    totp_core.generate_backup_codes.return_value = ["AAAAA-BBBBB"]
    totp_core.verify_code.return_value = False
    monkeypatch.setattr("app.services.totp_service.totp_core", totp_core)

    totp_encryption = MagicMock()
    totp_encryption.encrypt_secret.return_value = "iv:tag:cipher"
    totp_encryption.decrypt_secret.return_value = "DECRYPTED_SECRET"
    monkeypatch.setattr("app.services.totp_service.totp_encryption", totp_encryption)

    monkeypatch.setattr(
        "app.services.totp_service.async_get_password_hash",
        AsyncMock(side_effect=lambda c: f"hash:{c}"),
    )
    monkeypatch.setattr(
        "app.services.totp_service.async_verify_password",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.totp_service.is_bcrypt_hash",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.totp_service.verify_password_any",
        MagicMock(return_value=False),
    )

    db = MagicMock()
    db.commit = AsyncMock()
    svc = TOTPService(db)
    # 测试期便捷访问（mock 实例每次 _make_service 调用独立创建）
    svc._totp_core = totp_core
    svc._totp_encryption = totp_encryption
    return svc


# ---- is_enabled / is_setup ----


async def test_is_enabled_returns_false_when_no_record(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.repo.get.return_value = None

    assert await svc.is_enabled(1) is False
    svc.repo.get.assert_awaited_once_with(1)


async def test_is_enabled_returns_true_when_record_enabled(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.repo.get.return_value = MagicMock(enabled=True)

    assert await svc.is_enabled(1) is True


async def test_is_setup_returns_false_when_no_record(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.repo.get.return_value = None

    assert await svc.is_setup(1) is False


# ---- setup ----


async def test_setup_generates_secret_encrypts_stores_returns_dict(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.repo.upsert_pending.return_value = MagicMock()

    result = await svc.setup(1, "user@example.com")

    assert set(result.keys()) == {"secret", "otpauth_uri", "backup_codes"}
    assert result["secret"] == "JBSWY3DPEHPK3PXP"
    assert result["otpauth_uri"] == "otpauth://totp/test"
    assert result["backup_codes"] == ["AAAAA-BBBBB"]

    # upsert_pending(user_id, secret_encrypted, hashed_backup_codes)
    svc.repo.upsert_pending.assert_awaited_once()
    args = svc.repo.upsert_pending.await_args.args
    assert args[0] == 1
    assert args[1] == "iv:tag:cipher"  # encrypt_secret 输出
    assert args[2] == ["hash:AAAAA-BBBBB"]  # 经 async_get_password_hash 哈希
    svc.db.commit.assert_awaited_once()


# ---- confirm ----


async def test_confirm_raises_not_setup_when_no_record(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.repo.get.return_value = None

    with pytest.raises(ValidationException) as exc:
        await svc.confirm(1, "123456")

    assert exc.value.error_code == ErrorCode.Auth.TWO_FACTOR_NOT_SETUP
    svc.repo.enable.assert_not_called()


async def test_confirm_raises_already_enabled_when_record_enabled(monkeypatch):
    svc = _make_service(monkeypatch)
    svc.repo.get.return_value = MagicMock(enabled=True, secret_encrypted="enc")

    with pytest.raises(ValidationException) as exc:
        await svc.confirm(1, "123456")

    assert exc.value.error_code == ErrorCode.Auth.TWO_FACTOR_ALREADY_ENABLED
    svc.repo.enable.assert_not_called()


async def test_confirm_raises_totp_invalid_when_code_wrong(monkeypatch):
    svc = _make_service(monkeypatch)
    # verify_code 默认 False
    svc.repo.get.return_value = MagicMock(enabled=False, secret_encrypted="enc")

    with pytest.raises(ValidationException) as exc:
        await svc.confirm(1, "000000")

    assert exc.value.error_code == ErrorCode.Auth.TOTP_INVALID
    svc.repo.enable.assert_not_called()


async def test_confirm_enables_on_valid_code(monkeypatch):
    svc = _make_service(monkeypatch)
    svc._totp_core.verify_code.return_value = True
    record = MagicMock(enabled=False, secret_encrypted="enc")
    svc.repo.get.return_value = record

    await svc.confirm(1, "123456")

    svc.repo.enable.assert_awaited_once_with(record)
    svc.db.commit.assert_awaited_once()


# ---- verify ----


async def test_verify_returns_true_when_2fa_not_enabled(monkeypatch):
    """未启用 2FA 直接放行（passthrough）。"""
    svc = _make_service(monkeypatch)
    svc.repo.get.return_value = None

    assert await svc.verify(1, "123456") is True


async def test_verify_returns_true_when_totp_matches(monkeypatch):
    svc = _make_service(monkeypatch)
    svc._totp_core.verify_code.return_value = True
    record = MagicMock(enabled=True, secret_encrypted="enc", backup_codes=[])
    svc.repo.get.return_value = record

    assert await svc.verify(1, "123456") is True
    # TOTP 命中不应消耗备用码
    svc.repo.set_backup_codes.assert_not_called()


async def test_verify_returns_false_when_no_code_matches(monkeypatch):
    svc = _make_service(monkeypatch)
    # verify_code 默认 False；async_verify_password 默认 False
    record = MagicMock(
        enabled=True, secret_encrypted="enc", backup_codes=["$2b$hashed"]
    )
    svc.repo.get.return_value = record

    assert await svc.verify(1, "000000") is False
    # 无备用码命中 → 不应落库
    svc.repo.set_backup_codes.assert_not_called()
    svc.db.commit.assert_not_called()


# ---- disable / regenerate ----


async def test_disable_deletes_record_after_successful_verification(monkeypatch):
    svc = _make_service(monkeypatch)
    svc._totp_core.verify_code.return_value = True
    record = MagicMock(enabled=True, secret_encrypted="enc", backup_codes=[])
    svc.repo.get.return_value = record

    await svc.disable(1, "123456")

    svc.repo.delete.assert_awaited_once_with(1)
    svc.db.commit.assert_awaited_once()


async def test_regenerate_backup_codes_returns_new_codes_after_verification(
    monkeypatch,
):
    svc = _make_service(monkeypatch)
    svc._totp_core.verify_code.return_value = True
    svc._totp_core.generate_backup_codes.return_value = ["NEW1-AAAA", "NEW2-BBBB"]
    record = MagicMock(enabled=True, secret_encrypted="enc", backup_codes=[])
    svc.repo.get.return_value = record

    result = await svc.regenerate_backup_codes(1, "123456")

    assert result == ["NEW1-AAAA", "NEW2-BBBB"]
    # 新备用码经哈希后落库
    svc.repo.set_backup_codes.assert_awaited_once()
    args = svc.repo.set_backup_codes.await_args.args
    assert args[0] is record
    assert args[1] == ["hash:NEW1-AAAA", "hash:NEW2-BBBB"]
    svc.db.commit.assert_awaited_once()
