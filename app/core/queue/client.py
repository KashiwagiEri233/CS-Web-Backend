"""任务投递入口（enqueue）+ 可降级 eager 回退。

依赖方向：本模块依赖 core（config/logger/tasks），**core 不依赖本模块**。
任何 service 要用队列才 `from app.core.queue import enqueue`；不用队列的项目
可整建删除 `app/core/queue/`，核心无感。

arq 仅在真正需要投递到 broker 时**惰性 import**——所以"未装 arq + eager 执行"
这条路径不会触发 import 错误。
"""

import os
from typing import Any, Optional

from app.core.config import settings
from app.core.loguru_logger import get_logger
from app.core.queue.tasks import TASKS

logger = get_logger("queue")

_TASK_NAMES = {fn.__name__ for fn in TASKS}


def _read_queue_enabled() -> bool:
    """队列总开关。**刻意不放进核心 `Settings`**——保持 core 不依赖 queue，删本模块即净。

    优先读真实环境变量 `QUEUE_ENABLED`；缺失时回退 `ENV_FILE` 指向的 .env 文件
    （与 config.py 同源，因 pydantic 不会把 .env 值写入 os.environ），
    使 .env 里写 `QUEUE_ENABLED=True` 同样生效。
    """
    val = os.getenv("QUEUE_ENABLED")
    if val is None:
        try:
            from dotenv import dotenv_values

            env_file = os.environ.get("ENV_FILE", ".env")
            val = dotenv_values(env_file).get("QUEUE_ENABLED")
        except Exception:  # noqa: BLE001 - 读取 .env 失败按未启用处理
            val = None
    return (
        str(val).strip().lower() in ("1", "true", "yes", "on")
        if val is not None
        else False
    )


_QUEUE_ENABLED = _read_queue_enabled()

# arq 连接池惰性单例（模式同 app/core/redis_client.py）
_pool: Any = None
_pool_initialized = False


def _eager_ctx() -> dict:
    """eager 降级模式下传给任务的最小 ctx（无 redis / 无 job_id）。"""
    return {"eager": True, "job_id": None, "job_try": 1, "redis": None}


async def _get_pool():
    """获取 arq 连接池；未配 broker / 未装 arq / 创建失败均返回 None（调用方走 eager）。"""
    global _pool, _pool_initialized
    if _pool_initialized:
        return _pool
    _pool_initialized = True

    if not settings.REDIS_URL:
        logger.info("队列: 未配置 REDIS_URL，enqueue 将就地同步执行 (eager)")
        return None

    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        _pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
        logger.info("队列: arq 连接池已创建")
    except ImportError:
        logger.error(
            "队列: QUEUE_ENABLED 但未安装 arq，回退 eager。"
            "启用请执行 pip install -r requirements-queue.txt"
        )
        _pool = None
    except Exception as exc:  # noqa: BLE001 - 创建失败不应阻断业务，降级 eager
        logger.error("队列: 连接池创建失败，回退 eager", error=str(exc))
        _pool = None

    return _pool


async def enqueue(task, *args, **kwargs) -> Optional[str]:
    """投递一个任务。

    Args:
        task: 在 `app/core/queue/tasks.py` 的 `TASKS` 注册的任务函数本身（非字符串）。
        *args / **kwargs: 传给任务（ctx 之后的参数）。

    Returns:
        真实投递时返回 arq job_id；**eager 降级模式下就地执行并返回 None**。

    降级：`QUEUE_ENABLED=False` / 未配 `REDIS_URL` / 未装 arq / 连接失败 → 就地 `await` 执行。
    """
    if task.__name__ not in _TASK_NAMES:
        raise ValueError(
            f"任务 {task.__name__} 未在 app/core/queue/tasks.py 的 TASKS 注册，"
            "worker 无法执行；请先登记。"
        )

    if not _QUEUE_ENABLED:
        await _run_eager(task, *args, **kwargs)
        return None

    pool = await _get_pool()
    if pool is None:
        await _run_eager(task, *args, **kwargs)
        return None

    job = await pool.enqueue_job(task.__name__, *args, **kwargs)
    job_id = job.job_id if job else None
    logger.info("队列: 任务已投递", task=task.__name__, job_id=job_id)
    return job_id


async def _run_eager(task, *args, **kwargs) -> None:
    """就地同步执行任务（降级路径）。"""
    logger.debug("队列(eager): 就地执行", task=task.__name__)
    await task(_eager_ctx(), *args, **kwargs)
    return None


async def close_queue_pool() -> None:
    """释放 arq 连接池。web 进程未显式调用也无妨（进程退出时连接随之关闭）。"""
    global _pool, _pool_initialized
    if _pool is not None:
        try:
            await _pool.aclose()
        except Exception:  # noqa: BLE001
            pass
    _pool = None
    _pool_initialized = False
