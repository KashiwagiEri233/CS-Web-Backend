"""进程内事件总线（async）：业务事件 → 订阅者（站内通知等副作用）。

语义与前端 appBus（src/shared/events/event-bus.ts）对齐：
- emit 立即返回：订阅者异步执行（fire-and-forget），失败仅记日志，不阻断业务。
- 单进程语义；多实例部署需要跨实例广播时（ADR-014 评估）再迁移到 Redis/arq。
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List

from app.core.loguru_logger import get_logger

logger = get_logger("events")

EventHandler = Callable[..., Awaitable[None]]


class EventBus:
    """进程内发布订阅总线。"""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[EventHandler]] = {}

    def subscribe(self, event: str, handler: EventHandler) -> None:
        """注册订阅者（幂等：重复注册同一 handler 忽略）。"""
        handlers = self._subscribers.setdefault(event, [])
        if handler not in handlers:
            handlers.append(handler)

    def emit(self, event: str, **data: Any) -> None:
        """发布事件：异步调度全部订阅者，立即返回。

        每个订阅者独立 asyncio task，互不阻塞；异常仅记日志。
        若当前无事件循环（如启动期），同步执行。
        """
        handlers = self._subscribers.get(event, [])
        if not handlers:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        for handler in handlers:
            coro = self._safe_run(handler, event, data)
            if loop is not None:
                loop.create_task(coro)
            else:
                asyncio.run(coro)

    async def _safe_run(self, handler: EventHandler, event: str, data: dict) -> None:
        try:
            await handler(**data)
        except Exception as exc:  # noqa: BLE001 - 订阅者失败不影响业务
            logger.error(
                "事件订阅者执行失败", event=event, error=str(exc), exc_info=exc
            )


# 模块级单例（与前端 appBus 同模式）
event_bus = EventBus()
