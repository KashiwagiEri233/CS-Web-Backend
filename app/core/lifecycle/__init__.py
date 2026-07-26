"""启动 / 关闭任务注册表（lifecycle registry）。

公开 API：
    from app.core.lifecycle import (
        register_shutdown,
        register_startup,
        run_shutdown,
        run_startup,
    )

    @register_startup("my_task", priority=50, critical=False)
    async def my_task() -> None:
        ...

用法约定与扩展指引见 ``docs/system/lifecycle.md``。

触发登记：``ensure_registrants_loaded()`` 在 ``run_startup`` / ``run_shutdown`` 入口
懒加载各注册点模块，使装饰器执行并填充注册表。**core 不在 import 期反向 import
service**，避免分层倒置与循环导入规避代码。

新增注册点：在 ``_CORE_REGISTRANT_MODULES`` 或 ``_SERVICE_REGISTRANT_MODULES`` 追加
模块路径即可（见下方常量）。
"""

from app.core.lifecycle.registry import (
    register_shutdown,
    register_startup,
    run_shutdown,
    run_startup,
)

__all__ = [
    "register_startup",
    "register_shutdown",
    "run_startup",
    "run_shutdown",
    "ensure_registrants_loaded",
]

# 基础设施注册点（core / database）：可在任意时刻 import
_CORE_REGISTRANT_MODULES: tuple[str, ...] = (
    "app.database",
    "app.core.observability",
    "app.core.redis_client",
)

# 业务域注册点（service）：仅在 run_startup/run_shutdown 时加载，
# 保持 core.lifecycle 不在 import 期依赖 service 层。
_SERVICE_REGISTRANT_MODULES: tuple[str, ...] = (
    "app.services.rbac_init",
    "app.services.exception_retention",
    "app.services.token_gc",
)

_registrants_loaded: bool = False


def ensure_registrants_loaded() -> None:
    """懒加载各启动 / 关闭任务的注册点模块，触发装饰器登记。

    幂等：多次调用只 import 一次。import 顺序与执行顺序无关（执行序由 priority 决定）。
    ``main.py`` 自身注册的任务在 ``app.main`` 被 import 时自登记，无需在此列出。
    """
    global _registrants_loaded
    if _registrants_loaded:
        return

    import importlib

    for module_path in _CORE_REGISTRANT_MODULES + _SERVICE_REGISTRANT_MODULES:
        importlib.import_module(module_path)

    _registrants_loaded = True
