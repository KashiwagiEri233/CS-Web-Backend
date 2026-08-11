"""并发/竞态集成测试（ER-44）：限流计数、令牌黑名单、refresh token 轮换。

真实 Redis + 真实 PostgreSQL 下用 ``asyncio.gather`` 并发压测三块核心类，
验证并发不变量（限流不超卖 / 黑名单拉黑后不失守 / refresh 轮换同族不重放），
区别于既有顺序测试（test_redis_backends.py 顺序原子性 + 故障恢复、
test_queue_worker.py arq 投递/消费）。

本地无法连接数据库/Redis 时自动 skip；CI 严格模式下直接失败。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app.core.config import settings
from app.core.rate_limit.backends import InMemoryBackend, RedisBackend
from app.core.rate_limit.limiter import DegradableRateLimiter
from app.core.security import (
    async_get_password_hash,
    generate_refresh_token,
    hash_refresh_token,
)
from app.core.security_blacklist import TokenBlacklist, _MemoryBlacklist
from app.core.timezone import now_utc
from app.database import get_session
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.auth_service import AuthService

pytestmark = pytest.mark.integration

_PASSWORD = "StrongPass1!"
_BLACKLIST_KEY_PREFIX = "jwt:blacklist:"


# ---------------------------------------------------------------- 限流并发（Redis）

async def test_rate_limit_redis_concurrent_no_oversell(integration_redis_client):
    """Redis 滑动窗口限流并发不超卖：30 并发恰 5 放行（Lua 原子性证明）。"""
    key = f"itest:conc-rate:{uuid.uuid4().hex}"
    backend = RedisBackend(integration_redis_client)
    try:
        results = await asyncio.gather(
            *[backend.is_allowed(key, calls=5, period=60) for _ in range(30)]
        )
        assert sum(results) == 5
    finally:
        await integration_redis_client.delete(key)


async def test_rate_limiter_redis_path_concurrent_no_oversell(integration_redis_client):
    """DegradableRateLimiter Redis 健康路径并发同样不超卖，且全程不触发降级。"""
    key = f"itest:conc-limiter:{uuid.uuid4().hex}"
    limiter = DegradableRateLimiter(
        RedisBackend(integration_redis_client),
        InMemoryBackend(),
        fallback="memory",
        retry_interval=5,
    )
    try:
        results = await asyncio.gather(
            *[limiter.is_allowed(key, calls=5, period=60) for _ in range(30)]
        )
        assert limiter.using_redis  # 全程 Redis 健康，未降级
        assert sum(results) == 5
    finally:
        await integration_redis_client.delete(key)


# ---------------------------------------------------------------- 黑名单并发（Redis）

async def test_blacklist_concurrent_add_same_jti_hits(integration_redis_client):
    """并发拉黑同一 jti（幂等）：结束后必命中，不抛异常。"""
    jti = f"itest-{uuid.uuid4().hex}"
    blacklist = TokenBlacklist(
        integration_redis_client, _MemoryBlacklist(), fallback="memory"
    )
    try:
        await asyncio.gather(*[blacklist.add(jti, 30) for _ in range(30)])
        assert await blacklist.contains(jti)
    finally:
        await integration_redis_client.delete(f"{_BLACKLIST_KEY_PREFIX}{jti}")


async def test_blacklist_concurrent_add_many_jti_isolated(integration_redis_client):
    """并发拉黑不同 jti：全部命中且互不干扰（key 隔离性）。"""
    jtis = [f"itest-{uuid.uuid4().hex}" for _ in range(20)]
    blacklist = TokenBlacklist(
        integration_redis_client, _MemoryBlacklist(), fallback="memory"
    )
    try:
        await asyncio.gather(*[blacklist.add(j, 30) for j in jtis])
        hits = await asyncio.gather(*[blacklist.contains(j) for j in jtis])
        assert all(hits)
    finally:
        for j in jtis:
            await integration_redis_client.delete(f"{_BLACKLIST_KEY_PREFIX}{j}")


class _FailingBlacklistRedis:
    """黑名单专用故障注入包装（setex/exists/delete）；恢复后转真实 Redis。"""

    def __init__(self, client) -> None:
        self.client = client
        self.failed = True

    async def setex(self, key, ttl, value):
        if self.failed:
            raise ConnectionError("injected redis outage")
        return await self.client.setex(key, ttl, value)

    async def exists(self, key):
        if self.failed:
            raise ConnectionError("injected redis outage")
        return await self.client.exists(key)

    async def delete(self, key):
        if self.failed:
            raise ConnectionError("injected redis outage")
        return await self.client.delete(key)


async def test_blacklist_concurrent_degraded_window_still_blocks(integration_redis_client):
    """降级窗口内并发 add/contains：内存兜底仍全部命中；Redis 恢复后双写仍命中。"""
    jtis = [f"itest-{uuid.uuid4().hex}" for _ in range(10)]
    toggle = _FailingBlacklistRedis(integration_redis_client)
    blacklist = TokenBlacklist(
        toggle, _MemoryBlacklist(), fallback="memory", retry_interval=0
    )
    try:
        await asyncio.gather(*[blacklist.add(j, 30) for j in jtis])
        hits = await asyncio.gather(*[blacklist.contains(j) for j in jtis])
        assert all(hits)
        assert not blacklist.using_redis  # 处于降级窗口

        toggle.failed = False  # Redis 恢复
        hits2 = await asyncio.gather(*[blacklist.contains(j) for j in jtis])
        assert all(hits2)  # add() 双写内存，恢复后仍命中
    finally:
        toggle.failed = False
        for j in jtis:
            await integration_redis_client.delete(f"{_BLACKLIST_KEY_PREFIX}{j}")


# ---------------------------------------------------------------- 令牌并发刷新（需 DB）


async def _make_user(db, sfx: str) -> int:
    user = User(
        username=f"itest_conc_{sfx}",
        email=f"itest_conc_{sfx}@t.com",
        hashed_password=await async_get_password_hash(_PASSWORD),
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    await db.commit()
    return user.id


async def _make_refresh_token(db, user_id: int, family_id: str, plain: str) -> int:
    rt = RefreshToken(
        user_id=user_id,
        token_hash=hash_refresh_token(plain),
        family_id=family_id,
        expires_at=now_utc() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ip_address=None,
        user_agent="itest-concurrency",
    )
    db.add(rt)
    await db.commit()
    return rt.id


async def _cleanup_user_tokens(db, user_ids: list[int]) -> None:
    """按 FK 依赖序清理鉴权侧挂靠行后删用户（与既有 HTTP 集成测试范式一致）。"""
    for table in (
        "refresh_tokens",
        "login_history",
        "password_history",
        "notifications",
        "two_factor_auth",
        "verification_codes",
        "password_reset_requests",
        "user_roles",
    ):
        try:
            async with db.begin_nested():
                await db.execute(
                    text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                    {"ids": user_ids},
                )
        except Exception:
            pass
    await db.execute(
        text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": user_ids}
    )
    await db.commit()


async def _refresh_once(plain: str):
    """独立 session 的并发刷新任务（模拟真实多请求：一请求一会话）。"""
    async with get_session() as db:
        return await AuthService(db).refresh_access_token(plain)


async def test_refresh_token_concurrent_rotation_single_family(integration_db_ready):
    """同一 refresh token 并发轮换：全部放行（宽限窗口 + family 活跃），
    新旧 token 同 family、原 token 必撤销、新 token 全部活跃。"""
    sfx = uuid.uuid4().hex[:8]
    family = uuid.uuid4().hex
    plain = generate_refresh_token()
    user_id = None
    async with get_session() as db:
        user_id = await _make_user(db, sfx)
        await _make_refresh_token(db, user_id, family, plain)
    try:
        pairs = await asyncio.gather(*[_refresh_once(plain) for _ in range(10)])
        new_plains = [p.refresh_token for p in pairs]
        assert len(set(new_plains)) == 10  # 各自签发互不相同的后继 token

        async with get_session() as db:
            rows = (
                (await db.execute(select(RefreshToken).where(RefreshToken.family_id == family)))
                .scalars()
                .all()
            )
            assert len(rows) == 11  # 原 1 + 新 10
            original = next(r for r in rows if r.token_hash == hash_refresh_token(plain))
            assert original.revoked_at is not None  # 原 token 必撤销
            new_rows = [r for r in rows if r.token_hash != hash_refresh_token(plain)]
            assert all(r.revoked_at is None for r in new_rows)  # 新 token 全活跃
            assert all(r.family_id == family for r in rows)
    finally:
        async with get_session() as db:
            await _cleanup_user_tokens(db, [user_id])


async def test_refresh_token_concurrent_revoke_race(integration_db_ready):
    """登出撤销与刷新并发竞争：不抛未预期异常，终态一致——
    原 token 必撤销；refresh 胜出则新 token 存在且活跃，撤销胜出则不产生新 token。"""
    sfx = uuid.uuid4().hex[:8]
    family = uuid.uuid4().hex
    plain = generate_refresh_token()
    user_id = None
    async with get_session() as db:
        user_id = await _make_user(db, sfx)
        await _make_refresh_token(db, user_id, family, plain)

    async def _revoke_once() -> bool:
        async with get_session() as db:
            return await AuthService(db).revoke_refresh_token(plain)

    refresh_ok = False
    try:
        results = await asyncio.gather(
            _refresh_once(plain), _revoke_once(), return_exceptions=True
        )
        refresh_result = results[0]
        if isinstance(refresh_result, Exception):
            # 撤销先胜出且 family 无后继 → 按复用处置拒绝
            assert type(refresh_result).__name__ == "InvalidCredentialsException"
        else:
            refresh_ok = True

        async with get_session() as db:
            rows = (
                (await db.execute(select(RefreshToken).where(RefreshToken.family_id == family)))
                .scalars()
                .all()
            )
            original = next(r for r in rows if r.token_hash == hash_refresh_token(plain))
            assert original.revoked_at is not None  # 无论谁胜出，原 token 必撤销
            new_rows = [r for r in rows if r.token_hash != hash_refresh_token(plain)]
            if refresh_ok:
                assert len(new_rows) == 1 and new_rows[0].revoked_at is None
            else:
                assert len(new_rows) == 0  # 撤销先提交，refresh 未创建新 token
    finally:
        async with get_session() as db:
            await _cleanup_user_tokens(db, [user_id])


async def test_revoke_all_then_refresh_rejected(integration_db_ready):
    """revoke_all（改密/封禁）先提交后，旧 token 刷新必须按复用拒绝——
    并发轮换的确定性对照基线（family 无活跃后继 → reuse 处置）。"""
    sfx = uuid.uuid4().hex[:8]
    family = uuid.uuid4().hex
    plain = generate_refresh_token()
    user_id = None
    async with get_session() as db:
        user_id = await _make_user(db, sfx)
        await _make_refresh_token(db, user_id, family, plain)
        await AuthService(db).revoke_all_user_tokens(user_id)
    try:
        with pytest.raises(Exception) as exc_info:
            await _refresh_once(plain)
        assert type(exc_info.value).__name__ == "InvalidCredentialsException"
    finally:
        async with get_session() as db:
            await _cleanup_user_tokens(db, [user_id])
