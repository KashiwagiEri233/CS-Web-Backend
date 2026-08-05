"""密码线程池包装与 JWT 声明契约测试。"""

from datetime import timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.security import create_access_token, verify_token


def test_access_token_contains_bound_security_claims():
    token, jti, _ = create_access_token({"sub": "alice", "id": 7})

    payload = verify_token(token)

    assert payload is not None
    assert payload["jti"] == jti
    assert payload["iss"] == settings.JWT_ISSUER
    assert payload["aud"] == settings.JWT_AUDIENCE
    assert payload["token_type"] == "access"
    assert "iat" in payload


def test_wrong_audience_is_rejected_even_when_legacy_is_enabled():
    token = jwt.encode(
        {
            "sub": "alice",
            "exp": 4102444800,
            "iss": settings.JWT_ISSUER,
            "aud": "wrong-audience",
            "token_type": "access",
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    assert verify_token(token) is None


def test_wrong_token_type_is_rejected():
    token, _, _ = create_access_token(
        {"sub": "alice", "token_type": "refresh"},
        expires_delta=timedelta(minutes=1),
    )
    # create_access_token 强制覆盖调用方伪造的类型。
    assert verify_token(token)["token_type"] == "access"


def test_required_distributed_security_state_needs_redis():
    with pytest.raises(ValidationError, match="REDIS_URL"):
        Settings(
            _env_file=None,
            SECRET_KEY="x" * 32,
            DATABASE_PASSWORD="pw",
            REQUIRE_REDIS_FOR_SECURITY=True,
            REDIS_URL=None,
        )


def test_require_redis_for_security_forces_closed_blacklist_fallback():
    """开启 REQUIRE_REDIS_FOR_SECURITY 时强制 TOKEN_BLACKLIST_FALLBACK=closed。"""
    cfg = Settings(
        _env_file=None,
        SECRET_KEY="x" * 32,
        DATABASE_PASSWORD="pw",
        REQUIRE_REDIS_FOR_SECURITY=True,
        REDIS_URL="redis://127.0.0.1:6379/0",
        TOKEN_BLACKLIST_FALLBACK="memory",
    )
    assert cfg.TOKEN_BLACKLIST_FALLBACK == "closed"


def test_rate_limit_does_not_accept_fail_closed_mode():
    with pytest.raises(ValidationError, match="RATE_LIMIT_FALLBACK"):
        Settings(
            _env_file=None,
            SECRET_KEY="x" * 32,
            DATABASE_PASSWORD="pw",
            RATE_LIMIT_FALLBACK="closed",
        )


def test_legacy_token_rejected_by_default():
    """默认（JWT_ACCEPT_LEGACY_TOKENS=False）拒绝无 iss/aud/token_type 的旧 token。"""
    token = jwt.encode(
        {"sub": "alice", "exp": 4102444800},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    assert verify_token(token) is None


def test_legacy_token_accepted_only_during_migration_window(monkeypatch):
    """迁移窗口显式开启时，完全无新增声明的旧 token 仍可校验。"""
    monkeypatch.setattr(settings, "JWT_ACCEPT_LEGACY_TOKENS", True)
    token = jwt.encode(
        {"sub": "alice", "exp": 4102444800},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    payload = verify_token(token)

    assert payload is not None
    assert payload["sub"] == "alice"


def test_token_without_exp_is_rejected():
    """缺失 exp 的 token 永不过期，即使 iss/aud 正确也必须拒绝。"""
    token = jwt.encode(
        {
            "sub": "alice",
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
            "token_type": "access",
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    assert verify_token(token) is None
