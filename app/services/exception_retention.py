"""异常日志保留期清理任务。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from app.core.config import settings
from app.core.lifecycle import register_startup
from app.core.loguru_logger import get_logger
from app.core.timezone import now_utc
from app.services.exception_service import ExceptionService

logger = get_logger("exception_retention")

_RETENTION_LOCK_KEY = 873924004


async def _purge_once() -> int:
    """在 PostgreSQL advisory lock 下执行一轮集群级清理。"""
    # 注意：get_session 必须保持方法内惰性导入（lifecycle → *_gc → repo → models → database → lifecycle 环）  # noqa: E501
    from app.database import get_session

    async with get_session() as db:
        lock_acquired = await db.scalar(
            text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
            {"lock_key": _RETENTION_LOCK_KEY},
        )
        if not lock_acquired:
            return 0
        cutoff = now_utc() - timedelta(days=settings.EXCEPTION_LOG_RETENTION_DAYS)
        return await ExceptionService(db).purge_before(cutoff)


@register_startup("exception_log_retention", priority=45, critical=False)
async def startup_exception_log_retention() -> None:
    """启动兜底清理一次；跨实例幂等由 ``_purge_once`` 内 advisory lock 保证。

    常驻循环已移除（避免每实例每 worker 各起空转循环）；周期调度已由
    ``app.core.queue.worker.WorkerSettings.cron_jobs``（arq cron 单点）承担
    （AR-S2 方案B 已落地）。此处仅做启动兜底（cold-start 兜底）。
    """
    interval = settings.EXCEPTION_LOG_CLEANUP_INTERVAL_SECONDS
    if interval <= 0:
        logger.info("异常日志保留期清理已禁用（间隔<=0）")
        return
    try:
        deleted = await _purge_once()
        if deleted:
            logger.info("异常日志保留期启动清理完成", deleted=deleted)
    except Exception as exc:  # noqa: BLE001 - 启动兜底可降级
        logger.warning(
            "异常日志保留期启动清理失败",
            error_type=type(exc).__name__,
            error=str(exc),
        )
