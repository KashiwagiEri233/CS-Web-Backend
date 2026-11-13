"""到期任务批处理：每个任务独立短事务，submitted 不自动退款。

调度通过 lifecycle 后台循环；测试环境与配置关闭时可由 CLI/测试直接调用
``run_expiry_batch``。
"""

from __future__ import annotations

import asyncio
from typing import Optional

from app.core.config import settings
from app.core.lifecycle import register_shutdown, register_startup
from app.core.loguru_logger import get_logger
from app.database import get_session
from app.repositories.task_repo import TaskRepository
from app.services.task.review_service import TaskReviewService

logger = get_logger("task_expiry")

_stop_event: Optional[asyncio.Event] = None


async def run_expiry_batch(limit: Optional[int] = None) -> dict:
    """扫描并处理一批到期任务；返回处理计数。"""
    batch = limit or settings.TASK_EXPIRY_BATCH_SIZE
    async with get_session() as db:
        task_ids = await TaskRepository(db).list_due_task_ids(limit=batch)
    expired = 0
    failed = 0
    for task_id in task_ids:
        async with get_session() as db:
            service = TaskReviewService(db)
            try:
                result = await service.expire_if_due(task_id=task_id)
                if result is None:
                    await db.rollback()
                    continue
                await db.commit()
                expired += 1
            except Exception as exc:  # noqa: BLE001 - 单任务失败不影响批次
                await db.rollback()
                failed += 1
                logger.warning(
                    "任务到期处理失败", task_id=task_id, error=str(exc)
                )
    return {"expired": expired, "failed": failed}


async def _expiry_loop() -> None:
    global _stop_event
    _stop_event = asyncio.Event()
    while not _stop_event.is_set():
        try:
            await asyncio.wait_for(
                _stop_event.wait(), timeout=settings.TASK_EXPIRY_INTERVAL_SECONDS
            )
        except asyncio.TimeoutError:
            pass
        if _stop_event.is_set():
            break
        try:
            await run_expiry_batch()
        except Exception as exc:  # noqa: BLE001 - 后台循环持续运行
            logger.warning("到期任务批次异常", error=str(exc))


@register_startup("task_expiry_loop", priority=85, critical=False)
async def _start_expiry_loop() -> None:
    if settings.TESTING or not settings.TASK_EXPIRY_ENABLED:
        return
    asyncio.create_task(_expiry_loop())


@register_shutdown("task_expiry_loop", priority=15)
async def _stop_expiry_loop() -> None:
    if _stop_event is not None:
        _stop_event.set()
