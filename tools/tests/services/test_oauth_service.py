"""GitHub OAuth 服务测试：state 一次性校验、配置开关、code 换 token、回调聚合。

与 test_audit_service.py / test_email_service.py 风格一致：
- unittest.mock（AsyncMock / MagicMock / patch）
- asyncio_mode=auto，async def 测试函数不加 @pytest.mark.asyncio
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ErrorCode, ValidationException
from app.services import oauth_service
from app.services.oauth_service import OAuthService


def _make_httpx_client_mock(resp: MagicMock) -> MagicMock:
    """构造 httpx.AsyncClient 的 async context manager 替身。

    exchange_code 使用 ``async with httpx.AsyncClient(timeout=10) as client:``，
    因此 AsyncClient(...) 返回的对象需实现 __aenter__/__aexit__。
    """
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    client.get = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


# ---------------------------------------------------------------------- state


def test_generate_state_returns_64_char_hex_and_stores_it():
    svc = OAuthService()
    state = svc.generate_state()

    assert len(state) == 64
    assert all(c in "0123456789abcdef" for c in state)
    assert state in svc._states


def test_verify_state_succeeds_for_valid_state_and_deletes_it():
    svc = OAuthService()
    state = svc.generate_state()

    svc.verify_state(state)  # 不抛异常即通过

    assert state not in svc._states


def test_verify_state_raises_invalid_for_unknown_state():
    svc = OAuthService()

    with pytest.raises(ValidationException) as exc:
        svc.verify_state("unknown-state")

    assert exc.value.error_code == ErrorCode.Auth.OAUTH_STATE_INVALID


def test_verify_state_raises_expired_for_expired_state():
    svc = OAuthService()
    # 生成时时钟固定在 1000s，TTL=600s → 过期点 1600s
    with patch("app.services.oauth_service.time.time", return_value=1000.0):
        state = svc.generate_state()

    # 推进到 1601s（已过 TTL），校验应抛 OAUTH_STATE_EXPIRED
    with (
        patch("app.services.oauth_service.time.time", return_value=1601.0),
        pytest.raises(ValidationException) as exc,
    ):
        svc.verify_state(state)

    assert exc.value.error_code == ErrorCode.Auth.OAUTH_STATE_EXPIRED


def test_verify_state_is_one_time():
    svc = OAuthService()
    state = svc.generate_state()

    svc.verify_state(state)  # 首次校验通过并删除

    with pytest.raises(ValidationException) as exc:
        svc.verify_state(state)

    assert exc.value.error_code == ErrorCode.Auth.OAUTH_STATE_INVALID


# ------------------------------------------------------ configured / auth url


def test_configured_returns_false_when_client_id_empty():
    svc = OAuthService()

    with (
        patch.object(oauth_service.settings, "GITHUB_CLIENT_ID", None),
        patch.object(oauth_service.settings, "GITHUB_CLIENT_SECRET", "secret"),
    ):
        assert svc.configured is False


def test_configured_returns_true_when_both_id_and_secret_set():
    svc = OAuthService()

    with (
        patch.object(oauth_service.settings, "GITHUB_CLIENT_ID", "id123"),
        patch.object(oauth_service.settings, "GITHUB_CLIENT_SECRET", "secret"),
    ):
        assert svc.configured is True


def test_authorization_url_returns_none_when_not_configured():
    svc = OAuthService()

    with (
        patch.object(oauth_service.settings, "GITHUB_CLIENT_ID", None),
        patch.object(oauth_service.settings, "GITHUB_CLIENT_SECRET", "secret"),
    ):
        assert svc.authorization_url() is None


def test_authorization_url_returns_valid_url_with_client_id_and_state():
    svc = OAuthService()

    with (
        patch.object(oauth_service.settings, "GITHUB_CLIENT_ID", "id123"),
        patch.object(oauth_service.settings, "GITHUB_CLIENT_SECRET", "secret"),
        patch.object(oauth_service.settings, "GITHUB_CALLBACK_URL", "https://cb/cb"),
    ):
        url = svc.authorization_url()

    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=id123" in url
    assert "scope=user:email" in url
    assert "redirect_uri=https://cb/cb" in url
    # state 为 64 位 hex
    assert "state=" in url
    state_value = url.split("state=")[1]
    assert len(state_value) == 64
    assert all(c in "0123456789abcdef" for c in state_value)


# --------------------------------------------------------------- exchange_code


async def test_exchange_code_raises_not_configured_when_not_configured():
    svc = OAuthService()

    with (
        patch.object(oauth_service.settings, "GITHUB_CLIENT_ID", None),
        patch.object(oauth_service.settings, "GITHUB_CLIENT_SECRET", "secret"),
        pytest.raises(ValidationException) as exc,
    ):
        await svc.exchange_code("code123")

    assert exc.value.error_code == ErrorCode.Auth.OAUTH_NOT_CONFIGURED


async def test_exchange_code_raises_error_on_non_200_response():
    svc = OAuthService()
    resp = MagicMock()
    resp.status_code = 400
    resp.json.return_value = {}

    cm = _make_httpx_client_mock(resp)

    with (
        patch.object(oauth_service.settings, "GITHUB_CLIENT_ID", "id123"),
        patch.object(oauth_service.settings, "GITHUB_CLIENT_SECRET", "secret"),
        patch.object(oauth_service.settings, "GITHUB_CALLBACK_URL", "https://cb/cb"),
        patch("app.services.oauth_service.httpx.AsyncClient", return_value=cm),
        pytest.raises(ValidationException) as exc,
    ):
        await svc.exchange_code("code123")

    assert exc.value.error_code == ErrorCode.Auth.OAUTH_ERROR


async def test_exchange_code_raises_error_when_response_has_error_field():
    svc = OAuthService()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "error": "bad_verification_code",
        "error_description": "code invalid",
    }

    cm = _make_httpx_client_mock(resp)

    with (
        patch.object(oauth_service.settings, "GITHUB_CLIENT_ID", "id123"),
        patch.object(oauth_service.settings, "GITHUB_CLIENT_SECRET", "secret"),
        patch.object(oauth_service.settings, "GITHUB_CALLBACK_URL", "https://cb/cb"),
        patch("app.services.oauth_service.httpx.AsyncClient", return_value=cm),
        pytest.raises(ValidationException) as exc,
    ):
        await svc.exchange_code("code123")

    assert exc.value.error_code == ErrorCode.Auth.OAUTH_ERROR


# --------------------------------------------------------------- verify_callback


async def test_verify_callback_returns_user_info_dict_on_success():
    svc = OAuthService()
    state = svc.generate_state()

    svc.exchange_code = AsyncMock(return_value="access-token-123")
    svc._fetch_user = AsyncMock(
        return_value={
            "id": 12345,
            "login": "octocat",
            "name": "The Octocat",
            "avatar_url": "https://avatar.example/u",
            "html_url": "https://github.com/octocat",
        }
    )
    svc._fetch_primary_email = AsyncMock(return_value="USER@EXAMPLE.COM")

    result = await svc.verify_callback("code123", state)

    svc.exchange_code.assert_awaited_once_with("code123")
    svc._fetch_user.assert_awaited_once_with("access-token-123")
    svc._fetch_primary_email.assert_awaited_once_with("access-token-123")
    assert result == {
        "github_id": "12345",
        "email": "user@example.com",
        "login": "octocat",
        "name": "The Octocat",
        "avatar_url": "https://avatar.example/u",
        "html_url": "https://github.com/octocat",
    }


# ----------------------------------------------------------------- _callback_url


def test_callback_url_uses_github_callback_url_when_set():
    svc = OAuthService()

    with patch.object(
        oauth_service.settings, "GITHUB_CALLBACK_URL", "https://custom/cb"
    ):
        assert svc._callback_url() == "https://custom/cb"
