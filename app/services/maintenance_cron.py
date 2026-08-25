"""AR-S2 方案 B：周期维护任务的 arq cron 包装层。

arq 的 cron 协程会被注入 ``ctx`` 作为首个位置参数（arq ``worker.py`` 以
``coroutine(ctx, *args)`` 调用），而各 service 的 ``_purge_once()`` 不接受参数，
故在此用薄包装层接收 ``ctx`` 并转发。

单点保证：arq cron 任务按名注册、由 Redis 锁保证集群内仅一个 worker 执行本轮，
天然满足「多实例单点调度」。各 ``_purge_once`` 内部仍持 ``pg_try_advisory_xact_lock``
做二次兜底。

周期开关沿用各 service 既有 ``*_INTERVAL_SECONDS`` 设置（<=0 表示禁用），周期粒度
由 ``app.core.queue.worker.WorkerSettings.cron_jobs`` 的 cron 表达式决定。
"""

from __future__ import annotations

from app.core.config import settings
from app.services import data_retention, exception_retention, token_gc


async def token_gc_cron(ctx) -> int:
    """过期 refresh token 周期清理（每小时整点）。"""
    if settings.REFRESH_TOKEN_GC_INTERVAL_SECONDS <= 0:
        return 0
    return await token_gc._purge_once()


async def data_retention_cron(ctx) -> dict[str, int]:
    """登录历史 / 审计日志保留期清理（每日 03:00）。"""
    if (
        settings.LOGIN_HISTORY_CLEANUP_INTERVAL_SECONDS <= 0
        and settings.AUDIT_LOG_CLEANUP_INTERVAL_SECONDS <= 0
    ):
        return {"login_history": 0, "audit_log": 0}
    return await data_retention._purge_once()


async def exception_retention_cron(ctx) -> int:
    """异常日志保留期清理（每日 03:30）。"""
    if settings.EXCEPTION_LOG_CLEANUP_INTERVAL_SECONDS <= 0:
        return 0
    return await exception_retention._purge_once()
