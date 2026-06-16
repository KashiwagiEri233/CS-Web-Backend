"""refresh token 生命周期集成测试（需要可用的 PostgreSQL）。

覆盖：
1. issue_token_pair → refresh_access_token 轮换成功；
2. 旧 refresh token 被撤销后再用 → 复用检测 → 整个 family 失效；
3. revoke_all_user_tokens 撤销全部；
4. access token 黑名单（登出后失效）。

无法连接数据库时自动 skip。
"""

import uuid

import pytest
from sqlalchemy import text

from app.core.exceptions import InvalidCredentialsException
from app.core.security import (
    create_access_token,
    hash_refresh_token,
    verify_token,
)
from app.core.security_blacklist import get_blacklist
from app.database import engine, get_session
from app.models import Base  # noqa: F401  确保所有模型被注册到 metadata
from app.services.auth_service import AuthService


async def _db_available() -> bool:
    """探测数据库可用性。前一个测试的连接清理可能导致连接池瞬时不可用，重试一次。"""
    for attempt in range(2):
        try:
            async with get_session() as db:
                await db.execute(text("SELECT 1"))
            return True
        except Exception:
            if attempt == 0:
                import asyncio

                await asyncio.sleep(0.1)
                continue
            return False


async def _ensure_schema():
    """确保测试所需的表存在（create_all 仅在 app.main lifespan 中执行，
    测试不启动 app，需要显式建表）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
async def db_ready():
    """确保数据库可用且表已建。无 DB 时 skip。

    function 作用域：pytest-asyncio 0.21 的 event_loop 是 function scoped，
    无法与 module scoped fixture 组合。create_all 幂等，重复调用不会重建已存在的表。
    """
    if not await _db_available():
        pytest.skip("数据库不可用，跳过 refresh token 集成测试")
    await _ensure_schema()
    yield


async def _create_test_user(db, username: str) -> int:
    await db.execute(
        text(
            "INSERT INTO users (username,email,hashed_password,is_active,is_superuser) "
            "VALUES (:u,:e,'x',true,false)"
        ),
        {"u": username, "e": f"{username}@t.com"},
    )
    await db.commit()
    uid = (
        await db.execute(
            text("SELECT id FROM users WHERE username=:u"), {"u": username}
        )
    ).scalar()
    return uid


async def _cleanup(username: str, user_id: int) -> None:
    async with get_session() as db:
        await db.execute(text("DELETE FROM refresh_tokens WHERE user_id=:i"), {"i": user_id})
        await db.execute(text("DELETE FROM users WHERE id=:i"), {"i": user_id})
        await db.commit()


async def test_issue_then_refresh_rotation(db_ready):
    sfx = uuid.uuid4().hex[:8]
    uname = f"rtlife_u_{sfx}"

    async with get_session() as db:
        svc = AuthService(db)
        uid = await _create_test_user(db, uname)

        try:
            # 需要 user 对象，svc 内部按 id 查；这里直接构造
            from app.models.user import User

            user = await svc.user_repo.get_by_id(uid)
            pair = await svc.issue_token_pair(user)
            assert pair.access_token and pair.refresh_token

            old_refresh = pair.refresh_token
            old_hash = hash_refresh_token(old_refresh)

            # 用 refresh 换新
            pair2 = await svc.refresh_access_token(old_refresh)
            assert pair2.refresh_token != old_refresh
            assert pair2.access_token

            # 旧 token 已被轮换 → 再用应触发复用检测 → family 整体失效
            with pytest.raises(InvalidCredentialsException):
                await svc.refresh_access_token(old_refresh)

            # family 失效后，连新 token 也应失效（同 family）
            with pytest.raises(InvalidCredentialsException):
                await svc.refresh_access_token(pair2.refresh_token)
        finally:
            await _cleanup(uname, uid)


async def test_revoke_all_user_tokens(db_ready):
    sfx = uuid.uuid4().hex[:8]
    uname = f"rtrev_u_{sfx}"

    async with get_session() as db:
        svc = AuthService(db)
        uid = await _create_test_user(db, uname)

        try:
            from app.models.user import User

            user = await svc.user_repo.get_by_id(uid)
            # 签发多次（不同 family）
            p1 = await svc.issue_token_pair(user)
            p2 = await svc.issue_token_pair(user)

            # 全部撤销
            n = await svc.revoke_all_user_tokens(uid)
            assert n >= 2

            # 任一 refresh 都不能再换
            with pytest.raises(InvalidCredentialsException):
                await svc.refresh_access_token(p1.refresh_token)
            with pytest.raises(InvalidCredentialsException):
                await svc.refresh_access_token(p2.refresh_token)
        finally:
            await _cleanup(uname, uid)


async def test_access_blacklist_after_blacklist_add():
    """黑名单：加入 jti 后 is_access_revoked 应为 True。"""
    # 不依赖 DB，单独测黑名单与 access token 的协作
    token, jti, _exp = create_access_token({"sub": "x", "id": 1})
    payload = verify_token(token)
    assert payload is not None
    assert payload.get("jti") == jti

    bl = get_blacklist()
    # 加入黑名单（TTL 给足够长）
    remain = 60
    await bl.add(jti, remain)
    assert await bl.contains(jti)


async def test_blacklist_isolated_between_tokens():
    """不同 jti 互不影响。"""
    t1, jti1, _ = create_access_token({"sub": "x"})
    t2, jti2, _ = create_access_token({"sub": "y"})
    assert jti1 != jti2

    bl = get_blacklist()
    await bl.add(jti1, 60)
    assert await bl.contains(jti1)
    assert not await bl.contains(jti2)
