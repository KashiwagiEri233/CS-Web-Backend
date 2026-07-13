"""过期 refresh token 周期清理（lifecycle 启动后台任务）。"""

from __future__ import annotations

import asyncio
from typing import Optional

from app.core.config import settings
from app.core.lifecycle import register_shutdown, register_startup
from app.core.loguru_logger import get_logger

logger = get_logger("token_gc")

_gc_task: Optional[asyncio.Task] = None
_stop = asyncio.Event()


async def _purge_once() -> int:
    # 延迟 import，避免 lifecycle → token_gc → repo → models → database → lifecycle 环
    from app.database import get_session
    from app.repositories.refresh_token_repo import RefreshTokenRepository

    async with get_session() as db:
        n = await RefreshTokenRepository(db).purge_expired()
        await db.commit()
        return n


async def _gc_loop(interval: int) -> None:
    logger.info(f"refresh token GC 已启动，间隔 {interval}s")
    while not _stop.is_set():
        try:
            n = await _purge_once()
            if n:
                logger.info(f"refresh token GC 清理 {n} 行")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"refresh token GC 失败（已忽略）: {type(e).__name__}: {e}")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue
    logger.info("refresh token GC 已停止")


@register_startup("refresh_token_gc", priority=40, critical=False)
async def startup_refresh_token_gc() -> None:
    """启动后台 GC；间隔为 0 则禁用。"""
    global _gc_task
    interval = int(getattr(settings, "REFRESH_TOKEN_GC_INTERVAL_SECONDS", 0) or 0)
    if interval <= 0:
        logger.info("refresh token GC 已禁用（REFRESH_TOKEN_GC_INTERVAL_SECONDS<=0）")
        return
    _stop.clear()
    _gc_task = asyncio.create_task(_gc_loop(interval))


@register_shutdown("refresh_token_gc", priority=30)
async def shutdown_refresh_token_gc() -> None:
    global _gc_task
    _stop.set()
    if _gc_task is not None:
        try:
            await asyncio.wait_for(_gc_task, timeout=5)
        except Exception:  # noqa: BLE001
            _gc_task.cancel()
        _gc_task = None
