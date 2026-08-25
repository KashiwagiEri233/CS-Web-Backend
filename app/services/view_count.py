"""浏览计数写放大治理：Redis 计数 + 异步批量落库（lifecycle 启动后台任务）。

背景
----
原先 ``CommunityService.increment_view`` 每次浏览都会：① 查 ``has_viewed_recently``
（DB 读）② 插 ``CommunityPostView`` 行（DB 写）③ ``post.view_count += 1``
④ ``commit``。高读流量下写压力被放得很大。

新方案
------
- 去重：用 ``cache.incr(dedup_key)`` 做窗口去重——首次返回 1 并 ``expire``
  设置 TTL（复用 ``VIEW_DEDUP_WINDOW_HOURS``），重复返回 >1 即视为已浏览过、
  不计入。原子 ``incr`` 保证并发去重正确。
- 计数：``cache.incr(count_key)`` 原子累加，请求路径**不再触碰 DB、不再 commit**。
- 落库：本模块启动一个周期任务，把每篇帖的 Redis 计数用原子 ``getset(..., 0)``
  取回增量，单条批量 ``UPDATE ... view_count += delta`` + 一次 commit 落库。

正确性要点
----------
- ``getset`` 是原子的，因此即使多个 worker 进程各自 ``_pending`` 集合里都有同一
  篇帖，也只会有一个进程捕获到该次增量（另一个 ``getset`` 取到 0），不会重复累加。
- 落库失败（DB/Redis 抖动）时增量仍留在 Redis（``getset`` 未执行），下个周期再落，
  不会丢计数；仅 ``view_count`` 变为最终一致（秒级延迟）。
- 缓存降级到进程内存时，计数与去重退化为单进程语义（同进程内仍正确），与缓存层
  既有的「尽力而为」策略一致。Redis 在本部署为必选依赖。
"""

from __future__ import annotations

import asyncio
from typing import Optional, Set

from app.core.cache import get_cache
from app.core.config import settings
from app.core.constants import (
    SECONDS_PER_HOUR,
    VIEW_COUNT_FLUSH_INTERVAL_SECONDS,
    VIEW_DEDUP_WINDOW_HOURS,
)
from app.core.lifecycle import register_shutdown, register_startup
from app.core.loguru_logger import get_logger

logger = get_logger("view_count")

_pending: Set[int] = set()
_stop = asyncio.Event()

_DEDUP_KEY_PREFIX = "view:dedup:"
_COUNT_KEY_PREFIX = "view:count:"


def _dedup_key(post_id: int, user_id: Optional[int], ip_hash: Optional[str]) -> str:
    scope = f"u{user_id}" if user_id is not None else f"i{ip_hash}"
    return f"{_DEDUP_KEY_PREFIX}{post_id}:{scope}"


def _count_key(post_id: int) -> str:
    return f"{_COUNT_KEY_PREFIX}{post_id}"


async def record_view(
    post_id: int, *, user_id: Optional[int] = None, ip_hash: Optional[str] = None
) -> bool:
    """记录一次浏览。返回 True 表示计入（首次/窗口外），False 表示去重跳过。

    调用方（``CommunityService.increment_view``）负责先做「帖子存在且已发布」校验。
    """
    cache = get_cache()
    # 既无用户也无 IP 时无法去重，直接计数（极少见，用于匿名无 ip_hash 的兜底）。
    if user_id is None and ip_hash is None:
        await cache.incr(_count_key(post_id))
        _pending.add(post_id)
        return True
    n = await cache.incr(_dedup_key(post_id, user_id, ip_hash))
    if n == 1:
        await cache.expire(
            _dedup_key(post_id, user_id, ip_hash),
            VIEW_DEDUP_WINDOW_HOURS * SECONDS_PER_HOUR,
        )
    if n > 1:
        return False
    await cache.incr(_count_key(post_id))
    _pending.add(post_id)
    return True


async def _flush_once() -> int:
    # 延迟 import，避免 lifecycle → view_count → repo/models → database → lifecycle 环
    from app.database import get_session
    from app.models.community import CommunityPost
    from sqlalchemy import update as sa_update

    batch = list(_pending)
    if not batch:
        return 0
    cache = get_cache()
    deltas: dict[int, int] = {}
    for pid in batch:
        delta = await cache.getset(_count_key(pid), 0)
        if isinstance(delta, int) and delta > 0:
            deltas[pid] = delta
    # 无论是否落库成功，先把这批从 pending 移除（失败的增量仍留在 Redis，下轮再落）
    _pending.difference_update(batch)
    if not deltas:
        return 0
    async with get_session() as db:
        for pid, d in deltas.items():
            await db.execute(
                sa_update(CommunityPost)
                .where(CommunityPost.id == pid)
                .values(view_count=CommunityPost.view_count + d)
            )
        await db.commit()
    return sum(deltas.values())


async def _flush_loop(interval: int) -> None:
    logger.info(f"浏览计数落库任务已启动，间隔 {interval}s")
    while not _stop.is_set():
        try:
            n = await _flush_once()
            if n:
                logger.info(f"浏览计数落库 {n} 次增量")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"浏览计数落库失败（已忽略）: {type(e).__name__}: {e}")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue
    logger.info("浏览计数落库任务已停止")


@register_startup("view_count_flush", priority=42, critical=False)
async def startup_view_count_flush() -> None:
    """启动后台落库；间隔为 0 则禁用。"""
    global _flush_task
    interval = int(
        getattr(
            settings,
            "VIEW_COUNT_FLUSH_INTERVAL_SECONDS",
            VIEW_COUNT_FLUSH_INTERVAL_SECONDS,
        )
        or VIEW_COUNT_FLUSH_INTERVAL_SECONDS
    )
    if interval <= 0:
        logger.info("浏览计数落库已禁用（VIEW_COUNT_FLUSH_INTERVAL_SECONDS<=0）")
        return
    _stop.clear()
    _flush_task = asyncio.create_task(_flush_loop(interval))


@register_shutdown("view_count_flush", priority=28)
async def shutdown_view_count_flush() -> None:
    global _flush_task
    _stop.set()
    if _flush_task is not None:
        try:
            await asyncio.wait_for(_flush_task, timeout=5)
        except Exception:  # noqa: BLE001
            _flush_task.cancel()
        _flush_task = None


_flush_task: Optional[asyncio.Task] = None
