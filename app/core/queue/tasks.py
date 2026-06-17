"""任务定义与注册表。

每个任务是 `async def task(ctx, ...)`：
- `ctx`：arq 注入的上下文（含 `redis` / `job_id` / `job_try` 等）。
  **eager 降级模式下 ctx 是最小字典**（`{"eager": True, ...}`），任务不要依赖
  仅在真实 worker 下存在的键——用 `ctx.get(...)` 取值。
- 任务应**幂等、可重试**：可能因 worker 崩溃被重投。

新增任务：在此定义 `async def`，并加入下方 `TASKS` 列表（worker 与 enqueue 都据此注册/校验）。
"""

from app.core.loguru_logger import get_logger

logger = get_logger("queue.task")


async def example_send_notification(ctx, user_id: int, message: str) -> dict:
    """示例任务：演示签名/日志/返回值。真实任务把业务逻辑写在这里。

    注意：业务逻辑若要用 DB，应在任务内用 `async with get_session() as db:`
    自行管理会话（worker 进程没有请求级 `Depends(get_db)`）。
    """
    logger.info(
        "处理通知任务",
        user_id=user_id,
        message=message,
        eager=ctx.get("eager", False),
        job_try=ctx.get("job_try"),
    )
    # ... 实际业务（发信、生成报表、调用外部服务等）...
    return {"user_id": user_id, "delivered": True}


# 任务注册表：worker 的 functions 与 enqueue 的合法性校验都依赖它。
# 新增任务务必登记到这里，否则 enqueue 会拒绝投递（worker 也无法执行）。
TASKS = [
    example_send_notification,
]
