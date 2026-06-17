"""一键鉴权开关（AUTH_ENABLED）测试。不依赖数据库。"""

import pytest
from pydantic import ValidationError

from app.core.config import settings, Settings
from app.core.exceptions import BaseAppException
from app.dependencies import get_current_user


async def test_auth_disabled_returns_superuser(monkeypatch):
    """关闭鉴权时，无 token 也返回一个虚构超级用户。"""
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    user = await get_current_user(token=None, db=None)
    assert user.is_superuser is True
    assert user.is_active is True
    assert user.username == "auth-bypass"


async def test_auth_enabled_without_token_raises_401(monkeypatch):
    """开启鉴权时，无 token 返回 401（统一抛 BaseAppException 子类）。"""
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    with pytest.raises(BaseAppException) as ei:
        await get_current_user(token=None, db=None)
    assert ei.value.status_code == 401


def test_auth_disabled_in_production_is_rejected():
    """生产安全锁：DEBUG=False 时关闭鉴权应拒绝（启动即失败）。"""
    with pytest.raises(ValidationError):
        Settings(
            SECRET_KEY="x",
            DATABASE_PASSWORD="pw",
            AUTH_ENABLED=False,
            DEBUG=False,
        )


def test_auth_disabled_allowed_in_debug():
    s = Settings(
        SECRET_KEY="x",
        DATABASE_PASSWORD="pw",
        AUTH_ENABLED=False,
        DEBUG=True,
    )
    assert s.AUTH_ENABLED is False
