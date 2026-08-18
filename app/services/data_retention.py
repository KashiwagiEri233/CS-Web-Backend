"""数据保留期清理任务：登录历史（默认 90 天）与审计日志（默认 365 天）。

遵循 ``exception_retention.py`` / ``token_gc.py`` 的既定模式：
advisory lock 保证集群级单实例执行，``asyncio.Event`` 控制优雅停止。
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from app.core.config import settings
from app.core.lifecycle import register_startup
from app.core.loguru_logger import get_logger
from app.core.timezone import now_utc

logger = get_logger("data_retention")

_RETENTION_LOCK_KEY = 873924005


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


@register_startup("data_retention", priority=46, critical=False)
async def startup_data_retention() -> None:
    """启动兜底清理一次；跨实例幂等由 ``_purge_once`` 内 advisory lock 保证。

    常驻循环已移除（避免每实例每 worker 各起空转循环）；周期调度已由
    ``app.core.queue.worker.WorkerSettings.cron_jobs``（arq cron 单点）承担
    （AR-S2 方案B 已落地）。此处仅做启动兜底（cold-start 兜底）。
    """
    login_interval = settings.LOGIN_HISTORY_CLEANUP_INTERVAL_SECONDS
    audit_interval = settings.AUDIT_LOG_CLEANUP_INTERVAL_SECONDS
    if login_interval <= 0 and audit_interval <= 0:
        logger.info("数据保留期清理已禁用（两间隔均<=0）")
        return
    try:
        result = await _purge_once()
        if result["login_history"] or result["audit_log"]:
            logger.info(
                "数据保留期启动清理完成",
                login_history_deleted=result["login_history"],
                audit_log_deleted=result["audit_log"],
            )
    except Exception as exc:  # noqa: BLE001 - 启动兜底可降级
        logger.warning(
            "数据保留期启动清理失败",
            error_type=type(exc).__name__,
            error=str(exc),
        )
