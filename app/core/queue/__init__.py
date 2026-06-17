"""异步任务队列（arq）—— 可选模块。

公开 API：
    from app.core.queue import enqueue
    await enqueue(some_task, arg1, kw=...)

**可选**：不用队列的项目无需安装 arq（见 requirements-queue.txt），也可整建删除本目录，
核心层不依赖它。详见 docs/system/queue.md。

注意：本 `__init__` 不 import arq、也不 import worker——保证"未装 arq + eager 执行"路径可用。
"""

from app.core.queue.client import close_queue_pool, enqueue
from app.core.queue.tasks import TASKS

__all__ = ["enqueue", "close_queue_pool", "TASKS"]
