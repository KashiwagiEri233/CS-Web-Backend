"""进程内 + 跨实例事件总线（async）：业务事件 → 订阅者（站内通知等副作用）。

语义与前端 appBus（src/shared/events/event-bus.ts）对齐：
- emit 立即返回：订阅者异步执行（fire-and-forget），失败仅记日志，不阻断业务。
- 单进程语义为默认（MULTI_INSTANCE=False，零开销）。
- 多实例部署（MULTI_INSTANCE=True，ADR-014 已落地）：emit 在本地调度的同时，
  经 arq 广播事件到所有 worker 实例；每个 worker 在 on_startup 注册本地订阅者，
  收到广播后在自身进程内再跑一遍订阅者，实现跨实例。广播路径通过 broadcast=False
  避免回环（worker 内 emit 不再二次投递）。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.core.loguru_logger import get_logger

logger = get_logger("events")

# 无运行事件循环时（如启动期 emit）的应急 loop：复用而非反复 asyncio.run
# 新建/关闭（ER-56：多次各建/关 loop 仅启动期触发，复用消除浪费）。
_EMERGENCY_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _run_without_loop(coro: Awaitable[Any]) -> Any:
    """无运行事件循环时执行协程：复用模块级应急 loop。"""
    global _EMERGENCY_LOOP
    if _EMERGENCY_LOOP is None or _EMERGENCY_LOOP.is_closed():
        _EMERGENCY_LOOP = asyncio.new_event_loop()
    return _EMERGENCY_LOOP.run_until_complete(coro)


# 跨实例广播总开关：默认关闭（单实例，行为与改造前完全一致）。
_MULTI_INSTANCE = os.getenv("MULTI_INSTANCE", "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

EventHandler = Callable[..., Awaitable[None]]


class EventBus:
    """进程内发布订阅总线，可选跨实例广播（arq）。"""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[EventHandler]] = {}

    def subscribe(self, event: str, handler: EventHandler) -> None:
        """注册订阅者（幂等：重复注册同一 handler 忽略）。"""
        handlers = self._subscribers.setdefault(event, [])
        if handler not in handlers:
            handlers.append(handler)

    def emit(self, event: str, broadcast: bool = True, **data: Any) -> None:
        """发布事件：异步调度全部本地订阅者，立即返回。

        每个订阅者独立 asyncio task，互不阻塞；异常仅记日志。
        若当前无事件循环（如启动期），同步执行。

        Args:
            broadcast: True 且 MULTI_INSTANCE 开启时，额外经 arq 广播到其它实例。
                跨实例落地的 worker 在自身进程内调用 emit 时会传 broadcast=False，
                避免无限回环。
        """
        self._dispatch_local(event, data)

        if broadcast and _MULTI_INSTANCE:
            self._broadcast(event, data)

    def _dispatch_local(self, event: str, data: dict) -> None:
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
                _run_without_loop(coro)

    def _broadcast(self, event: str, data: dict) -> None:
        """跨实例广播：经 arq 投递到所有 worker 实例（fire-and-forget）。

        惰性 import 队列模块，确保 core 不反向依赖 queue（保持删除 queue 即净）。
        投递失败/未启用/未配 Redis 时静默降级为本地已执行（不阻断业务）。
        """
        try:
            from app.core.queue import enqueue

            from app.core.queue.tasks import dispatch_event_broadcast

            loop = asyncio.get_running_loop()
            loop.create_task(enqueue(dispatch_event_broadcast, event, data))
        except RuntimeError:
            # 无运行循环（启动期等），直接同步发起，不阻断。
            try:
                from app.core.queue import enqueue

                from app.core.queue.tasks import dispatch_event_broadcast

                _run_without_loop(enqueue(dispatch_event_broadcast, event, data))
            except Exception as exc:  # noqa: BLE001
                logger.warning("事件跨实例广播失败", event=event, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - 广播失败不阻断本地业务
            logger.warning(
                "事件跨实例广播失败，仅本地已执行",
                event=event,
                error=str(exc),
            )

    async def _safe_run(self, handler: EventHandler, event: str, data: dict) -> None:
        try:
            await handler(**data)
        except Exception as exc:  # noqa: BLE001 - 订阅者失败不影响业务
            logger.error(
                "事件订阅者执行失败", event=event, error=str(exc), exc_info=exc
            )


# 模块级单例（与前端 appBus 同模式）
event_bus = EventBus()
