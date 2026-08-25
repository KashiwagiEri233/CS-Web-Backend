"""管理员强制 2FA 开关（ADMIN_2FA_REQUIRED）测试。不依赖数据库。

覆盖：
- 生产安全锁：APP_ENV=production 时关闭强制 2FA 拒绝启动；
- 开发/测试环境允许关闭；
- Admin2FARequired 豁免分支：APP_ENV=development + 关开关时管理员免 2FA 放行；
- 未豁免时（生产/默认）管理员未启用 2FA 仍拒绝（回归 TWO_FACTOR_NOT_SETUP）。
"""

import pytest
from pydantic import ValidationError

from app.core.config import settings, Settings
from app.core.exceptions import ValidationException
from app.middleware.rbac import Admin2FARequired
from app.models.user import User


def _build_settings(**kw) -> Settings:
    """构造 Settings（必填密钥由 .env.test / 环境变量提供，kwargs 覆盖测试字段）。

    默认 TESTING=False：安全锁对 TESTING 豁免，避免 .env.test 的 TESTING=True
    让「生产拒绝」类断言失效；测试需 TESTING=True 时显式传。
    """
    defaults = {"TESTING": False}
    defaults.update(kw)
    return Settings(
        SECRET_KEY="x" * 32,
        DATABASE_PASSWORD="pw",
        TOTP_ENCRYPTION_KEY="y" * 32,
        COMMUNITY_IP_HASH_SECRET="z" * 16,
        **defaults,
    )


def _admin_user() -> User:
    """超级用户（管理员判定：is_superuser=True）。"""
    return User(
        username="admin-toggle-test",
        email="admin-toggle-test@example.com",
        hashed_password="x",
        is_superuser=True,
    )


# ------------------------------------------------------------------ 生产安全锁


def test_admin_2fa_disabled_in_production_is_rejected():
    """生产安全锁：APP_ENV=production 时关闭强制 2FA 应拒绝（启动即失败）。"""
    with pytest.raises(ValidationError):
        _build_settings(APP_ENV="production", ADMIN_2FA_REQUIRED=False)


def test_admin_2fa_disabled_allowed_in_development():
    """开发环境（APP_ENV=development）允许关闭强制 2FA。"""
    s = _build_settings(APP_ENV="development", ADMIN_2FA_REQUIRED=False)
    assert s.ADMIN_2FA_REQUIRED is False


def test_admin_2fa_disabled_allowed_in_testing():
    """测试进程（TESTING=True）允许关闭强制 2FA（单测需构造各种配置）。"""
    s = _build_settings(APP_ENV="production", ADMIN_2FA_REQUIRED=False, TESTING=True)
    assert s.ADMIN_2FA_REQUIRED is False


def test_admin_2fa_enabled_by_default_in_production():
    """生产环境默认开启强制 2FA（安全默认）。"""
    s = _build_settings(APP_ENV="production")
    assert s.ADMIN_2FA_REQUIRED is True


# ------------------------------------------------------------------ 豁免分支


async def test_admin_2fa_bypassed_in_development(monkeypatch):
    """开发环境豁免：APP_ENV=development + 关开关时，管理员免 2FA 直接放行。"""
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "ADMIN_2FA_REQUIRED", False)
    checker = Admin2FARequired()
    user = await checker(current_user=_admin_user(), db=None)
    assert user.is_superuser is True


async def test_admin_2fa_still_required_in_production(monkeypatch):
    """生产不豁免：默认配置下管理员未启用 2FA 仍拒绝（TWO_FACTOR_NOT_SETUP）。"""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ADMIN_2FA_REQUIRED", True)
    from app.services.totp_service import TOTPService

    async def _fake_is_enabled(self, user_id: int) -> bool:
        return False  # 管理员未启用 2FA

    monkeypatch.setattr(TOTPService, "is_enabled", _fake_is_enabled)
    checker = Admin2FARequired()
    with pytest.raises(ValidationException) as ei:
        await checker(current_user=_admin_user(), db=None)
    assert ei.value.error_code == "TWO_FACTOR_NOT_SETUP"
