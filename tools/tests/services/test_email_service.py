"""邮件发送服务测试：smtplib 线程池发送 + 开发模式控制台回退。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import email_service
from app.services.email_service import (
    _send_sync,
    _smtp_transport,
    send_mail,
    send_verification_code,
)


def test_smtp_transport_returns_none_when_host_empty():
    with patch.object(email_service.settings, "SMTP_HOST", ""):
        assert _smtp_transport() is None


def test_smtp_transport_uses_smtp_ssl_when_secure_true():
    with (
        patch.object(email_service.settings, "SMTP_HOST", "smtp.example.com"),
        patch.object(email_service.settings, "SMTP_PORT", 465),
        patch.object(email_service.settings, "SMTP_SECURE", True),
        patch.object(email_service.settings, "SMTP_TLS_SKIP_VERIFY", False),
        patch.object(email_service.settings, "SMTP_USER", None),
        patch("app.services.email_service.smtplib.SMTP_SSL") as smtp_ssl,
        patch("app.services.email_service.smtplib.SMTP") as smtp_plain,
    ):
        result = _smtp_transport()

    smtp_ssl.assert_called_once_with("smtp.example.com", 465, timeout=10)
    smtp_plain.assert_not_called()
    assert result is smtp_ssl.return_value


def test_smtp_transport_uses_plain_smtp_and_starttls_when_secure_false():
    with (
        patch.object(email_service.settings, "SMTP_HOST", "smtp.example.com"),
        patch.object(email_service.settings, "SMTP_PORT", 587),
        patch.object(email_service.settings, "SMTP_SECURE", False),
        patch.object(email_service.settings, "SMTP_TLS_SKIP_VERIFY", False),
        patch.object(email_service.settings, "SMTP_USER", None),
        patch("app.services.email_service.smtplib.SMTP_SSL") as smtp_ssl,
        patch("app.services.email_service.smtplib.SMTP") as smtp_plain,
    ):
        result = _smtp_transport()

    smtp_plain.assert_called_once_with("smtp.example.com", 587, timeout=10)
    smtp_plain.return_value.starttls.assert_called_once_with()
    smtp_ssl.assert_not_called()
    assert result is smtp_plain.return_value


def test_smtp_transport_logs_in_when_user_set():
    with (
        patch.object(email_service.settings, "SMTP_HOST", "smtp.example.com"),
        patch.object(email_service.settings, "SMTP_PORT", 587),
        patch.object(email_service.settings, "SMTP_SECURE", False),
        patch.object(email_service.settings, "SMTP_TLS_SKIP_VERIFY", False),
        patch.object(email_service.settings, "SMTP_USER", "user@example.com"),
        patch.object(email_service.settings, "SMTP_PASS", "secret"),
        patch("app.services.email_service.smtplib.SMTP") as smtp_plain,
    ):
        result = _smtp_transport()

    smtp_plain.return_value.login.assert_called_once_with("user@example.com", "secret")
    assert result is smtp_plain.return_value


def test_smtp_transport_calls_ehlo_when_tls_skip_verify():
    with (
        patch.object(email_service.settings, "SMTP_HOST", "smtp.example.com"),
        patch.object(email_service.settings, "SMTP_PORT", 465),
        patch.object(email_service.settings, "SMTP_SECURE", True),
        patch.object(email_service.settings, "SMTP_TLS_SKIP_VERIFY", True),
        patch.object(email_service.settings, "SMTP_USER", None),
        patch("app.services.email_service.smtplib.SMTP_SSL") as smtp_ssl,
    ):
        _smtp_transport()

    smtp_ssl.return_value.ehlo.assert_called_once_with()


def test_send_sync_logs_when_transport_none():
    transport_mock = MagicMock()
    transport_mock.quit = MagicMock()
    with (
        patch("app.services.email_service._smtp_transport", return_value=None),
        patch.object(email_service.logger, "info") as logger_info,
    ):
        _send_sync("a@b.com", "subj", "body")

    assert logger_info.call_count == 2
    transport_mock.quit.assert_not_called()


def test_send_sync_sends_email_via_transport_sendmail():
    transport = MagicMock()
    with (
        patch("app.services.email_service._smtp_transport", return_value=transport),
        patch.object(email_service.settings, "SMTP_FROM", "no-reply@example.com"),
        patch.object(email_service.logger, "info") as logger_info,
    ):
        _send_sync("a@b.com", "subj", "body")

    transport.sendmail.assert_called_once()
    args, _ = transport.sendmail.call_args
    assert args[0] == "no-reply@example.com"
    assert args[1] == ["a@b.com"]
    assert "Subject: subj" in args[2]
    assert "a@b.com" in args[2]
    logger_info.assert_not_called()


def test_send_sync_calls_transport_quit_in_finally():
    transport = MagicMock()
    with (
        patch("app.services.email_service._smtp_transport", return_value=transport),
        patch.object(email_service.settings, "SMTP_FROM", "no-reply@example.com"),
    ):
        _send_sync("a@b.com", "subj", "body")

    transport.quit.assert_called_once_with()


def test_send_sync_does_not_raise_when_quit_fails():
    transport = MagicMock()
    transport.quit.side_effect = Exception("quit failed")
    with (
        patch("app.services.email_service._smtp_transport", return_value=transport),
        patch.object(email_service.settings, "SMTP_FROM", "no-reply@example.com"),
    ):
        # Should not raise even though quit fails.
        _send_sync("a@b.com", "subj", "body")

    transport.sendmail.assert_called_once()
    transport.quit.assert_called_once_with()


def test_send_sync_propagates_sendmail_failure_after_quit_attempted():
    transport = MagicMock()
    transport.sendmail.side_effect = RuntimeError("send failed")
    with (
        patch("app.services.email_service._smtp_transport", return_value=transport),
        patch.object(email_service.settings, "SMTP_FROM", "no-reply@example.com"),
    ):
        with pytest.raises(RuntimeError, match="send failed"):
            _send_sync("a@b.com", "subj", "body")

    # quit is still attempted in finally block.
    transport.quit.assert_called_once_with()


async def test_send_mail_calls_asyncio_to_thread_with_send_sync():
    with patch(
        "app.services.email_service.asyncio.to_thread", new=AsyncMock()
    ) as to_thread:
        await send_mail("a@b.com", "subj", "body")

    to_thread.assert_awaited_once_with(_send_sync, "a@b.com", "subj", "body", None)


async def test_send_verification_code_calls_send_mail_with_subject_and_code():
    with (
        patch.object(email_service.settings, "VERIFICATION_CODE_TTL_MINUTES", 10),
        patch(
            "app.services.email_service.send_mail", new=AsyncMock()
        ) as send_mail_mock,
    ):
        await send_verification_code("user@example.com", "123456")

    send_mail_mock.assert_awaited_once()
    args, kwargs = send_mail_mock.call_args
    assert args[0] == "user@example.com"
    assert args[1] == "【FZTBU】验证码"
    assert "123456" in args[2]
    assert "10" in args[2]
    html = kwargs["html"]
    for digit in "123456":
        assert digit in html
    assert "${" not in html
    assert 'Content-Type' not in html
