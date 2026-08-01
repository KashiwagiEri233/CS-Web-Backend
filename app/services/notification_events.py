"""通知事件订阅：业务事件 → 站内通知（与前端 notification-events.ts 对齐）。

当前订阅：
- user.registered → 欢迎通知

订阅者自带独立会话（get_session），业务事务提交后再 emit 即可安全使用。
多实例部署需跨实例广播时（ADR-014），把订阅者内实现迁移到 arq 队列任务。
"""

from __future__ import annotations

from app.core.events import event_bus
from app.core.loguru_logger import get_logger
from app.database import get_session
from app.services.notification_service import NotificationService

logger = get_logger("notification.events")


async def _on_user_registered(user_id: int) -> None:
    async with get_session() as db:
        service = NotificationService(db)
        await service.create(
            user_id=user_id,
            type="system",
            title="欢迎加入",
            content="欢迎加入我们的社区！在这里你可以参与各类活动，结识志同道合的伙伴。",
        )


def register_notification_events() -> None:
    """注册全部通知订阅者（幂等，可多次调用）。"""
    event_bus.subscribe("user.registered", _on_user_registered)
    logger.debug("通知事件订阅已注册")
