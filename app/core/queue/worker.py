"""arq worker 进程入口。

启动（独立于 web 进程）：
    arq app.core.queue.worker.WorkerSettings

仅在启动 worker 时才会被 import（此时 arq 必装、REDIS_URL 必配）；web 进程不 import 本模块。
"""

from arq.connections import RedisSettings

from app.core.config import settings
from app.core.loguru_logger import get_logger
from app.core.queue.tasks import TASKS

logger = get_logger("queue.worker")

if not settings.REDIS_URL:
    # worker 必须有 broker。web 进程不会走到这里（它只 import client，不 import worker）。
    raise RuntimeError(
        "启动 arq worker 需要配置 REDIS_URL（broker）；请在环境中配置后再启动 worker。"
    )

_BROKER_URL = settings.REDIS_URL
assert _BROKER_URL is not None


async def on_startup(ctx) -> None:
    # 每个 worker 实例注册本地通知订阅者；配合事件总线跨实例广播（ADR-014），
    # 收到广播后在自身进程内运行订阅者，实现多实例事件一致。
    from app.services.notification_events import register_notification_events

    register_notification_events()
    logger.info("arq worker 启动", tasks=[fn.__name__ for fn in TASKS])


async def on_shutdown(ctx) -> None:
    logger.info("arq worker 关闭")


class WorkerSettings:
    """arq 读取此类来配置 worker。新增任务只需登记到 tasks.TASKS。"""

    functions = TASKS
    redis_settings = RedisSettings.from_dsn(_BROKER_URL)
    on_startup = on_startup
    on_shutdown = on_shutdown
    # 默认重试/超时可按需加：max_tries / job_timeout / keep_result 等。
