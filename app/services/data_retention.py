"""数据保留期清理任务：登录历史（默认 90 天）与审计日志（默认 365 天）。

遵循 ``exception_retention.py`` / ``token_gc.py`` 的既定模式：
advisory lock 保证集群级单实例执行，``asyncio.Event`` 控制优雅停止。
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Optional

from app.core.constants import SECONDS_PER_DAY
from sqlalchemy import text

from app.core.config import settings
from app.core.lifecycle import register_shutdown, register_startup
from app.core.loguru_logger import get_logger
from app.core.timezone import now_utc

logger = get_logger("data_retention")

_RETENTION_LOCK_KEY = 873924005
_cleanup_task: Optional[asyncio.Task] = None
_stop = asyncio.Event()


async def _purge_once() -> dict[str, int]:
    """在 PostgreSQL advisory lock 下执行一轮集群级清理。"""
    from app.database import get_session
    from app.repositories.audit_log_repo import AuditLogRepository
    from app.repositories.login_history_repo import LoginHistoryRepository

    result: dict[str, int] = {"login_history": 0, "audit_log": 0}

    async with get_session() as db:
        lock_acquired = await db.scalar(
            text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
            {"lock_key": _RETENTION_LOCK_KEY},
        )
        if not lock_acquired:
            return result

        # 登录历史保留期清理
        login_cutoff = now_utc() - timedelta(
            days=settings.LOGIN_HISTORY_RETENTION_DAYS
        )
        login_repo = LoginHistoryRepository(db)
        result["login_history"] = await login_repo.purge_before(login_cutoff)

        # 审计日志保留期清理
        audit_cutoff = now_utc() - timedelta(
            days=settings.AUDIT_LOG_RETENTION_DAYS
        )
        audit_repo = AuditLogRepository(db)
        result["audit_log"] = await audit_repo.delete_before(audit_cutoff)

        await db.commit()

    return result


async def _cleanup_loop(interval: int) -> None:
    """启动时立即清理，之后按配置间隔重复。"""
    while not _stop.is_set():
        try:
            deleted = await _purge_once()
            if deleted["login_history"] or deleted["audit_log"]:
                logger.info(
                    "数据保留期清理完成",
                    login_history_deleted=deleted["login_history"],
                    audit_log_deleted=deleted["audit_log"],
                )
        except Exception as exc:  # noqa: BLE001 - 后台维护任务可降级
            logger.warning(
                "数据保留期清理失败",
                error_type=type(exc).__name__,
                error=str(exc),
            )
        try:
            await asyncio.wait_for(_stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


@register_startup("data_retention", priority=46, critical=False)
async def startup_data_retention() -> None:
    """启动数据保留期清理；两个间隔均为 0 时禁用。"""
    global _cleanup_task
    login_interval = settings.LOGIN_HISTORY_CLEANUP_INTERVAL_SECONDS
    audit_interval = settings.AUDIT_LOG_CLEANUP_INTERVAL_SECONDS
    # 取两者中较小的间隔作为执行周期（每次都检查两张表，跳过无需清理的）
    interval = min(login_interval or SECONDS_PER_DAY, audit_interval or SECONDS_PER_DAY)
    if login_interval <= 0 and audit_interval <= 0:
        logger.info("数据保留期清理已禁用")
        return
    _stop.clear()
    _cleanup_task = asyncio.create_task(_cleanup_loop(interval))


@register_shutdown("data_retention", priority=24)
async def shutdown_data_retention() -> None:
    """停止数据保留期后台任务。"""
    global _cleanup_task
    _stop.set()
    if _cleanup_task is not None:
        try:
            await asyncio.wait_for(_cleanup_task, timeout=5)
        except Exception:  # noqa: BLE001
            _cleanup_task.cancel()
        _cleanup_task = None
