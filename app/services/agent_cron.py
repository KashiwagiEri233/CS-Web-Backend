"""AG-P3-06 起步切片：Agent 专项定时任务的 arq cron 包装层。

与 ``maintenance_cron.py`` 同构：薄包装接收 arq 注入的 ``ctx`` 并转发；
Redis 锁由 arq cron 注册天然保证（集群内单 worker 执行本轮）。

当前两个 sweep：
1. ``agent_inbox_sweep_cron``：收件箱惰性回收的定时化——snoozed 到期回
   pending、pending 过期转 expired（AG-P3-01 状态机的读路径惰性回收之外
   的兜底，保证「稍后」到期即回队列，不依赖用户是否打开工作台）。
2. ``event_auto_archive_cron``：过期活动归档（上游性能 PR 从读路径移除
   auto_archive 时，docstring 明确约定「供定时任务或管理任务调用」——
   本任务即该约定的兑现）。
"""

from __future__ import annotations

from app.core.config import settings
from app.core.loguru_logger import get_logger
from app.core.timezone import now_utc
from app.database import get_session
from app.repositories.agent_inbox_repo import AgentInboxRepository
from app.services.event.event_service import EventService

logger = get_logger("agent.cron")


async def agent_inbox_sweep_cron(ctx) -> dict[str, int]:
    """收件箱回收（每 15 分钟）：snooze 到期回 pending / pending 过期转 expired。"""
    if not settings.AGENT_SWEEPS_ENABLED:
        return {"promoted": 0, "expired": 0}
    now = now_utc()
    async with get_session() as db:
        repo = AgentInboxRepository(db)
        promoted = await repo.promote_all_due_snoozes(now)
        expired = await repo.expire_all_stale(now)
        await db.commit()
    if promoted or expired:
        logger.info(
            "agent_inbox_sweep 完成",
            promoted=promoted,
            expired=expired,
        )
    return {"promoted": promoted, "expired": expired}


async def event_auto_archive_cron(ctx) -> int:
    """过期活动归档（每日 00:10）：日期已过的 upcoming → ended。"""
    if not settings.AGENT_SWEEPS_ENABLED:
        return 0
    async with get_session() as db:
        count = await EventService(db).auto_archive()
    if count:
        logger.info("event_auto_archive 完成", archived=count)
    return count
