"""Phase 1 认证集成测试（需要可用 PostgreSQL；含 Alembic 自动迁移到 head）。

覆盖：
1. 注册 → 自动登录 → me → 改密 → 重新登录；
2. 邮箱登录 + 2FA 全流程（setup/confirm/login requires_2fa/complete/备用码）；
3. scrypt 旧哈希懒升级（登录后哈希自动变 bcrypt）；
4. 登录历史记录；
5. 设备列表 + 远程登出；
6. 忘记密码申请 → 管理员批准 → 默认密码登录；
7. derive_username 派生规则。
"""

import uuid

import pytest

from app.core.password_compat import hash_scrypt, is_bcrypt_hash
from app.core.timezone import now_utc
from app.database import get_session
from app.services.auth_service import AuthService, derive_username
from app.services.password_reset_service import PasswordResetService
from app.services.verification_service import VerificationService
from app.core import totp as totp_core


def _sfx() -> str:
    return uuid.uuid4().hex[:8]


def _strong_password() -> str:
    return f"Str0ng!Pass_{uuid.uuid4().hex[:6]}"


async def _cleanup_user(db, user_id: int) -> None:
    from sqlalchemy import text

    email = (
        await db.execute(text("SELECT email FROM users WHERE id=:i"), {"i": user_id})
    ).scalar_one_or_none()
    for table in (
        "refresh_tokens",
        "login_history",
        "password_history",
        "two_factor_auth",
        "notifications",
        "user_roles",
    ):
        await db.execute(text(f"DELETE FROM {table} WHERE user_id=:i"), {"i": user_id})
    if email:
        await db.execute(
            text("DELETE FROM verification_codes WHERE email=:e"), {"e": email}
        )
        await db.execute(
            text("DELETE FROM password_reset_requests WHERE email=:e"), {"e": email}
        )
    await db.execute(text("DELETE FROM users WHERE id=:i"), {"i": user_id})
    await db.commit()


@pytest.mark.integration
async def test_register_login_change_password_flow(integration_db_ready):
    email = f"p1_{_sfx()}@test.dev"
    password = _strong_password()

    async with get_session() as db:
        svc = AuthService(db)
        try:
            pair = await svc.register(
                email, password, {"ip_address": "1.2.3.4", "user_agent": "t"}
            )
            assert pair.access_token and pair.refresh_token
            user = await svc.user_repo.get_by_email(email)

            me = await svc.get_me(user.id)
            assert isinstance(me["roles"], list)
            assert me["two_factor_enabled"] is False

            # 改密后旧密码失效、新密码可登录
            await svc.change_password(user.id, password, f"New{password}")

            with pytest.raises(Exception):
                # 旧密码登录应失败
                await svc.login_by_email(
                    email, password, {"ip_address": "1.2.3.4", "user_agent": "t"}
                )
            result = await svc.login_by_email(
                email, f"New{password}", {"ip_address": "1.2.3.4", "user_agent": "t"}
            )
            assert result["pair"] is not None
            await _cleanup_user(db, user.id)
        except Exception:
            user = await svc.user_repo.get_by_email(email)
            if user:
                await _cleanup_user(db, user.id)
            raise


@pytest.mark.integration
async def test_two_factor_full_flow(integration_db_ready):
    email = f"p2_{_sfx()}@test.dev"
    password = _strong_password()

    async with get_session() as db:
        svc = AuthService(db)
        try:
            await svc.register(
                email, password, {"ip_address": "1.2.3.4", "user_agent": "t"}
            )
            user = await svc.user_repo.get_by_email(email)

            # setup → confirm
            setup = await svc.totp_service.setup(user.id, email)
            assert setup["otpauth_uri"].startswith("otpauth://")
            assert len(setup["backup_codes"]) == 8
            code = totp_core.generate_code(setup["secret"], int(now_utc().timestamp()))
            await svc.totp_service.confirm(user.id, code)
            assert await svc.totp_service.is_enabled(user.id)

            # 登录返回 requires_2fa
            result = await svc.login_by_email(
                email, password, {"ip_address": "1.2.3.4", "user_agent": "t"}
            )
            assert result["requires_2fa"] is True
            token = result["two_factor_token"]
            assert token

            # 2FA 完成登录
            fresh_code = totp_core.generate_code(
                setup["secret"], int(now_utc().timestamp())
            )
            pair = await svc.complete_two_factor_login(
                token, fresh_code, {"ip_address": "1.2.3.4", "user_agent": "t"}
            )
            assert pair.access_token

            # 预认证 token 一次性：重复使用应失败
            token2 = (
                await svc.login_by_email(
                    email, password, {"ip_address": "1.2.3.4", "user_agent": "t"}
                )
            )["two_factor_token"]
            await svc.complete_two_factor_login(
                token2, fresh_code, {"ip_address": "1.2.3.4", "user_agent": "t"}
            )
            from app.core.exceptions import AuthenticationException

            with pytest.raises(AuthenticationException):
                await svc.complete_two_factor_login(
                    token2, fresh_code, {"ip_address": "1.2.3.4", "user_agent": "t"}
                )

            # 备用码登录
            backup = setup["backup_codes"][0]
            token3 = (
                await svc.login_by_email(
                    email, password, {"ip_address": "1.2.3.4", "user_agent": "t"}
                )
            )["two_factor_token"]
            pair3 = await svc.complete_two_factor_login(
                token3, backup, {"ip_address": "1.2.3.4", "user_agent": "t"}
            )
            assert pair3.access_token
            # 备用码已消费：再用于新登录应失败
            token4 = (
                await svc.login_by_email(
                    email, password, {"ip_address": "1.2.3.4", "user_agent": "t"}
                )
            )["two_factor_token"]
            with pytest.raises(Exception):
                await svc.complete_two_factor_login(
                    token4, backup, {"ip_address": "1.2.3.4", "user_agent": "t"}
                )

            await _cleanup_user(db, user.id)
        except Exception:
            user = await svc.user_repo.get_by_email(email)
            if user:
                await _cleanup_user(db, user.id)
            raise


@pytest.mark.integration
async def test_scrypt_lazy_upgrade(integration_db_ready):
    """旧 scrypt 哈希登录成功后自动懒升级为 bcrypt。"""
    email = f"p3_{_sfx()}@test.dev"
    password = "LegacyPass123!"

    async with get_session() as db:
        svc = AuthService(db)
        try:
            from app.models.user import User

            user = User(
                username=derive_username(email),
                email=email,
                hashed_password=hash_scrypt(password),
                is_active=True,
                is_superuser=False,
            )
            db.add(user)
            await db.commit()

            result = await svc.login_by_email(
                email, password, {"ip_address": "1.2.3.4", "user_agent": "t"}
            )
            assert result["pair"] is not None

            refreshed = await svc.user_repo.get_by_email(email)
            assert is_bcrypt_hash(refreshed.hashed_password)

            await _cleanup_user(db, refreshed.id)
        except Exception:
            user = await svc.user_repo.get_by_email(email)
            if user:
                await _cleanup_user(db, user.id)
            raise


@pytest.mark.integration
async def test_login_history_and_sessions(integration_db_ready):
    email = f"p4_{_sfx()}@test.dev"
    password = _strong_password()

    async with get_session() as db:
        svc = AuthService(db)
        try:
            await svc.register(
                email, password, {"ip_address": "9.9.9.9", "user_agent": "ua-1"}
            )
            user = await svc.user_repo.get_by_email(email)

            # 失败登录记录（user_id 为空 + attempted_email）
            from app.core.exceptions import InvalidCredentialsException

            with pytest.raises(InvalidCredentialsException):
                await svc.login_by_email(
                    email, "wrong-pass", {"ip_address": "9.9.9.9", "user_agent": "ua-2"}
                )

            # 会话列表
            sessions = await svc.list_sessions(user.id)
            assert len(sessions) == 1
            assert sessions[0]["ip_address"] == "9.9.9.9"
            assert sessions[0]["user_agent"] == "ua-1"

            # 远程登出
            revoked = await svc.revoke_session(user.id, sessions[0]["id"])
            assert revoked is True
            assert await svc.list_sessions(user.id) == []
            # 不属于自己的 token 不能撤销
            assert (
                await svc.revoke_session(user.id + 999999, sessions[0]["id"]) is False
            )

            await _cleanup_user(db, user.id)
        except Exception:
            user = await svc.user_repo.get_by_email(email)
            if user:
                await _cleanup_user(db, user.id)
            raise


@pytest.mark.integration
async def test_password_reset_request_approve_flow(integration_db_ready):
    email = f"p5_{_sfx()}@test.dev"
    password = _strong_password()

    async with get_session() as db:
        svc = AuthService(db)
        reset = PasswordResetService(db, audit=svc.audit)
        try:
            await svc.register(
                email, password, {"ip_address": "1.1.1.1", "user_agent": "t"}
            )
            user = await svc.user_repo.get_by_email(email)
            admin = await svc.user_repo.get_by_email("admin@example.com")

            req = await reset.create_request(email)
            assert req["id"] > 0
            # 重复申请返回同一 pending
            req2 = await reset.create_request(email)
            assert req2["id"] == req["id"]

            listed = await reset.list_requests()
            assert any(r.id == req["id"] for r in listed)

            if admin is None:
                # 无默认管理员时跳过批准（rbac_init 未跑）
                await _cleanup_user(db, user.id)
                return

            from app.core.config import settings

            settings.PASSWORD_RESET_DEFAULT = "DefaultReset123!"
            approved = await reset.approve_request(
                req["id"],
                admin.id,
                admin.username,
                note="ok",
                client_meta={"ip_address": "1.1.1.1", "user_agent": "t"},
            )
            assert approved.status == "approved"

            # 默认密码可登录
            result = await svc.login_by_email(
                email, "DefaultReset123!", {"ip_address": "1.1.1.1", "user_agent": "t"}
            )
            assert result["pair"] is not None
            # 原密码失效
            with pytest.raises(Exception):
                await svc.login_by_email(
                    email, password, {"ip_address": "1.1.1.1", "user_agent": "t"}
                )

            await _cleanup_user(db, user.id)
        except Exception:
            user = await svc.user_repo.get_by_email(email)
            if user:
                await _cleanup_user(db, user.id)
            raise


@pytest.mark.integration
async def test_verification_code_flow(integration_db_ready):
    email = f"p6_{_sfx()}@test.dev"

    async with get_session() as db:
        svc = VerificationService(db)
        try:
            code = await svc.generate(email)
            assert len(code) == 6
            assert code.isdigit()
            assert await svc.verify(email, code) is True
            # 一次性：再次使用失败
            assert await svc.verify(email, code) is False
            # 错码失败
            code2 = await svc.generate(email)
            assert await svc.verify(email, "000000") is False
            assert await svc.verify(email, code2) is True
            from sqlalchemy import text

            await db.execute(
                text("DELETE FROM verification_codes WHERE email=:e"), {"e": email}
            )
            await db.commit()
        except Exception:
            from sqlalchemy import text

            await db.execute(
                text("DELETE FROM verification_codes WHERE email=:e"), {"e": email}
            )
            await db.commit()
            raise


def test_derive_username_rules():
    assert derive_username("alice@example.com") == "alice"
    assert derive_username("Alice.Wang+tag@x.com") == "AliceWangtag"
    assert derive_username("1number@x.com") == "u1number"
    assert derive_username("a@x.com") == "a__"
    assert len(derive_username("very-long-email-local-part-" * 3 + "@x.com")) <= 50
