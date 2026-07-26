"""启动 / 关闭任务注册表。

把应用启动 / 关闭的初始化逻辑从 ``app/main.py`` 解耦：各能力模块用
``@register_startup`` / ``@register_shutdown`` 装饰器**自注册**到全局注册表，
``lifespan`` 只调用 ``run_startup()`` / ``run_shutdown()`` 遍历执行——新增启动
任务无需回 ``main.py`` 改动（与项目「中心注册点」哲学一致）。

排序：任务带 ``priority``（int），启动按升序、关闭按**降序**（后启动的先关，
与启动顺序对称，依赖关系靠 priority 数字表达）。

失败传播：``critical=True`` 的启动任务失败 → 记 error 后 **raise**（拒绝启动，
对应「DB 连接失败必须 fail fast」）；``critical=False`` 失败 → 仅记 warning 继续
（对应「Redis 可降级」）。关闭阶段一律当非 critical——异常吞掉只记日志，绝不让
关闭阶段的错误掩盖 / 干扰启动阶段的诊断。

线程安全：装饰器在模块 import 期由主线程执行（Python 导入串行且持 GIL），无并发
问题；``run_*`` 内不做动态注册。各注册点模块需被 import 才会触发登记，触发动作
集中在 ``app/core/lifecycle/__init__.py`` 末尾（见该文件注释）。
"""

from dataclasses import dataclass
from typing import Awaitable, Callable, List

from app.core.loguru_logger import get_logger

logger = get_logger("lifecycle")


@dataclass(frozen=True)
class StartupTask:
    """启动任务条目。"""

    name: str
    func: Callable[[], Awaitable[None]]
    priority: int
    critical: bool


@dataclass(frozen=True)
class ShutdownTask:
    """关闭任务条目（无 critical：关闭阶段尽力执行，失败不抛）。"""

    name: str
    func: Callable[[], Awaitable[None]]
    priority: int


# 全局注册表（模块级单例，import 期填充）
_STARTUP_TASKS: List[StartupTask] = []
_SHUTDOWN_TASKS: List[ShutdownTask] = []

# 已注册的任务名（启动 / 关闭各自独立命名空间，防同名重复注册导致行为歧义）
_STARTUP_NAMES: set[str] = set()
_SHUTDOWN_NAMES: set[str] = set()


def register_startup(
    name: str, priority: int = 50, critical: bool = True
) -> Callable[[Callable[[], Awaitable[None]]], Callable[[], Awaitable[None]]]:
    """装饰器：把一个协程函数登记为启动任务。

    Args:
        name: 任务唯一名（用于日志诊断；重名注册会抛 ValueError 防误用）。
        priority: 执行优先级，升序执行。约定：10=DB、20=seed、30=探测、90=展示。
        critical: True=失败拒绝启动；False=失败仅告警继续（增强项 / 降级项）。
    """
    if name in _STARTUP_NAMES:
        raise ValueError(f"启动任务 {name!r} 已注册，禁止重复登记")

    def decorator(func: Callable[[], Awaitable[None]]) -> Callable[[], Awaitable[None]]:
        _STARTUP_TASKS.append(
            StartupTask(name=name, func=func, priority=priority, critical=critical)
        )
        _STARTUP_NAMES.add(name)
        return func

    return decorator


def register_shutdown(
    name: str, priority: int = 50
) -> Callable[[Callable[[], Awaitable[None]]], Callable[[], Awaitable[None]]]:
    """装饰器：把一个协程函数登记为关闭任务。

    Args:
        name: 任务唯一名（重名注册会抛 ValueError）。
        priority: 执行优先级，**降序**执行（与启动升序对称；后启动的先关）。
    """
    if name in _SHUTDOWN_NAMES:
        raise ValueError(f"关闭任务 {name!r} 已注册，禁止重复登记")

    def decorator(func: Callable[[], Awaitable[None]]) -> Callable[[], Awaitable[None]]:
        _SHUTDOWN_TASKS.append(ShutdownTask(name=name, func=func, priority=priority))
        _SHUTDOWN_NAMES.add(name)
        return func

    return decorator


async def run_startup() -> None:
    """按 priority 升序执行所有已注册的启动任务。

    critical 任务失败抛出 → 中止启动（后续任务不再执行）；非 critical 失败 → 记
    warning 继续下一个任务。任务执行顺序以 priority 为准（同 priority 保持注册序）。

    入口先懒加载各注册点模块（见 ``ensure_registrants_loaded``），保证 service 层
    任务在 core 不反向 import 的前提下仍被登记。
    """
    # 延迟 import 避免 registry ↔ lifecycle 包循环
    from app.core.lifecycle import ensure_registrants_loaded

    ensure_registrants_loaded()

    for task in sorted(_STARTUP_TASKS, key=lambda t: (t.priority,)):
        try:
            logger.debug(f"启动任务开始: {task.name} (priority={task.priority})")
            await task.func()
        except Exception as exc:  # noqa: BLE001 - 注册表统一兜底
            if task.critical:
                logger.error(
                    f"关键启动任务失败，拒绝启动: {task.name}",
                    error=str(exc),
                )
                raise
            logger.warning(
                f"非关键启动任务失败，已降级继续: {task.name}",
                error=str(exc),
            )


async def run_shutdown() -> None:
    """按 priority 降序执行所有已注册的关闭任务（后启动的先关）。

    关闭阶段绝不让异常向外抛——任何任务失败都只记 warning，避免掩盖启动 / 业务
    异常或干扰进程退出码。
    """
    from app.core.lifecycle import ensure_registrants_loaded

    ensure_registrants_loaded()

    for task in sorted(_SHUTDOWN_TASKS, key=lambda t: t.priority, reverse=True):
        try:
            logger.debug(f"关闭任务开始: {task.name} (priority={task.priority})")
            await task.func()
        except Exception as exc:  # noqa: BLE001 - 关闭阶段一律吞错
            logger.warning(
                f"关闭任务异常（已忽略）: {task.name}",
                error=str(exc),
            )
