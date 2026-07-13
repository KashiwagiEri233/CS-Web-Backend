"""异常日志保留期清理任务。"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Optional

from sqlalchemy import text

from app.core.config import settings
from app.core.lifecycle import register_shutdown, register_startup
from app.core.loguru_logger import get_logger
from app.core.timezone import now_utc

logger = get_logger("exception_retention")

_RETENTION_LOCK_KEY = 873924004
_cleanup_task: Optional[asyncio.Task] = None
_stop = asyncio.Event()


async def _purge_once() -> int:
    """在 PostgreSQL advisory lock 下执行一轮集群级清理。"""
    from app.database import get_session
    from app.services.exception_service import ExceptionService

    async with get_session() as db:
        lock_acquired = await db.scalar(
            text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
            {"lock_key": _RETENTION_LOCK_KEY},
        )
        if not lock_acquired:
            return 0
        cutoff = now_utc() - timedelta(days=settings.EXCEPTION_LOG_RETENTION_DAYS)
        return await ExceptionService(db).purge_before(cutoff)


async def _cleanup_loop(interval: int) -> None:
    """启动时立即清理，之后按配置间隔重复。"""
    while not _stop.is_set():
        try:
            deleted = await _purge_once()
            if deleted:
                logger.info("异常日志保留期清理完成", deleted=deleted)
        except Exception as exc:  # noqa: BLE001 - 后台维护任务可降级
            logger.warning(
                "异常日志保留期清理失败",
                error_type=type(exc).__name__,
                error=str(exc),
            )
        try:
            await asyncio.wait_for(_stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


@register_startup("exception_log_retention", priority=45, critical=False)
async def startup_exception_log_retention() -> None:
    """启动异常日志保留期清理；间隔为 0 时禁用。"""
    global _cleanup_task
    interval = settings.EXCEPTION_LOG_CLEANUP_INTERVAL_SECONDS
    if interval <= 0:
        logger.info("异常日志保留期清理已禁用")
        return
    _stop.clear()
    _cleanup_task = asyncio.create_task(_cleanup_loop(interval))


@register_shutdown("exception_log_retention", priority=25)
async def shutdown_exception_log_retention() -> None:
    """停止异常日志保留期后台任务。"""
    global _cleanup_task
    _stop.set()
    if _cleanup_task is not None:
        try:
            await asyncio.wait_for(_cleanup_task, timeout=5)
        except Exception:  # noqa: BLE001
            _cleanup_task.cancel()
        _cleanup_task = None
