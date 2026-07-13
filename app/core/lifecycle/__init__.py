"""启动 / 关闭任务注册表（lifecycle registry）。

公开 API：
    from app.core.lifecycle import register_startup, register_shutdown, run_startup, run_shutdown

    @register_startup("my_task", priority=50, critical=False)
    async def my_task() -> None:
        ...

用法约定与扩展指引见 ``docs/system/lifecycle.md``。

触发登记：下方 ``_import_registrants()`` 在包 import 完成后立即 import 各注册点
模块，使装饰器在模块导入期执行并填充注册表。新增注册点只需在此处追加一行 import。
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
]


def _import_registrants() -> None:
    """显式 import 各启动 / 关闭任务的注册点模块，触发装饰器登记。

    import 顺序与执行顺序无关（执行序由 priority 决定）；此处仅保证这些模块被
    加载、装饰器被执行。显式 import（而非 entry_points 动态扫描）更可控、可追溯。

    main.py 自身注册的任务在 main 被 import 时自登记，无需在此导入。
    """
    # 局部 import 规避循环导入（这些模块会反向 import app.core.lifecycle 装饰器）
    from app import database  # noqa: F401  DB 初始化任务
    from app.core import observability, redis_client  # noqa: F401  OTel/Redis 任务
    from app.services import rbac_init  # noqa: F401  RBAC seed 任务
    from app.services import token_gc  # noqa: F401  refresh token GC


_import_registrants()
