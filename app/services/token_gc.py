"""过期 refresh token 周期清理（lifecycle 启动后台任务）。"""

from __future__ import annotations

from sqlalchemy import text

from app.core.config import settings
from app.core.lifecycle import register_startup
from app.core.loguru_logger import get_logger

logger = get_logger("token_gc")

_TOKEN_GC_LOCK_KEY = 873924003


async def _purge_once() -> int:
    # 延迟 import，避免 lifecycle → token_gc → repo → models → database → lifecycle 环
    from app.database import get_session
    from app.repositories.refresh_token_repo import RefreshTokenRepository

    async with get_session() as db:
        lock_acquired = await db.scalar(
            text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
            {"lock_key": _TOKEN_GC_LOCK_KEY},
        )
        if not lock_acquired:
            return 0
        n = await RefreshTokenRepository(db).purge_expired()
        await db.commit()
        return n


@register_startup("refresh_token_gc", priority=40, critical=False)
async def startup_refresh_token_gc() -> None:
    """启动兜底清理一次；跨实例幂等由 ``_purge_once`` 内 advisory lock 保证。

    常驻循环已移除（避免每实例每 worker 各起空转循环）；周期调度已由
    ``app.core.queue.worker.WorkerSettings.cron_jobs``（arq cron 单点）承担
    （AR-S2 方案B 已落地）。此处仅做启动兜底（cold-start 兜底）。
    """
    interval = int(getattr(settings, "REFRESH_TOKEN_GC_INTERVAL_SECONDS", 0) or 0)
    if interval <= 0:
        logger.info("refresh token GC 已禁用（间隔<=0）")
        return
    try:
        n = await _purge_once()
        if n:
            logger.info("refresh token GC 启动清理完成", deleted=n)
    except Exception as e:  # noqa: BLE001 - 启动兜底可降级
        logger.warning(
            f"refresh token GC 启动清理失败（已忽略）: {type(e).__name__}: {e}"
        )
