# 异步任务队列（arq）—— 可选模块

## 概述

把耗时操作（发信、生成报表、调外部服务、批处理）从请求里挪到后台 worker 异步执行。
基于 **arq**（async 原生、Redis 为 broker，复用 `REDIS_URL`）。

**这是一个可选、可删除的叶子模块**：
- 依赖方向只有 `queue → core`，**core 从不 import queue**——`main.py`、启动流程、核心层
  完全不碰它（已用测试断言保证）。
- 不用队列的项目**无需安装 arq**（不在主 `requirements.txt`），甚至可**整建删除
  `app/core/queue/`**，核心照常运行（顶多 `Settings` 留一个无害的 `QUEUE_ENABLED` 孤儿字段）。
- 关闭/未配时 `enqueue()` **就地同步执行（eager）**，功能不丢，只是不异步。

代码：`app/core/queue/`（`client.py` 投递、`tasks.py` 任务注册表、`worker.py` worker 入口）。

## 接口

| 符号 | 签名 | 用途 |
|---|---|---|
| `enqueue` | `await enqueue(task, *args, **kwargs) -> str \| None` | 投递任务；真实模式返回 job_id，eager 模式就地执行并返回 None |
| `close_queue_pool` | `await close_queue_pool() -> None` | 释放连接池（可不调，进程退出自动关） |
| `TASKS` | `list[Callable]` | 任务注册表（`tasks.py`） |
| `WorkerSettings` | class | arq worker 配置（`worker.py`） |

任务签名：`async def my_task(ctx, ...)`。`ctx` 是 arq 注入的上下文；**eager 降级模式下 ctx 是
最小字典**（`{"eager": True, ...}`），任务请用 `ctx.get(...)` 取值，不要依赖仅真实 worker 下存在的键。

### 使用示例
```python
# 某 service 里（按需 opt-in，core 不强制）
from app.core.queue import enqueue
from app.core.queue.tasks import example_send_notification

await enqueue(example_send_notification, user_id=1, message="hi")
```

## 配置

`app/core/config.py`：`QUEUE_ENABLED`（默认 `False`）。broker 复用 `REDIS_URL`。

| 场景 | enqueue 行为 |
|---|---|
| `QUEUE_ENABLED=False`（默认） | eager：就地 `await` 执行 |
| `QUEUE_ENABLED=True` 但未配 `REDIS_URL` / 未装 arq / 连接失败 | eager（降级，记日志不报错） |
| `QUEUE_ENABLED=True` + `REDIS_URL` 可用 + arq 已装 | 真正投递到 broker，由 worker 异步执行 |

## 启用步骤

1. 装可选依赖：`pip install -r requirements-queue.txt`
2. 配置：`QUEUE_ENABLED=True` 且 `REDIS_URL=redis://...`
3. 起 worker（独立进程，与 web 分开）：
   ```bash
   arq app.core.queue.worker.WorkerSettings
   ```
4. web 侧照常 `await enqueue(task, ...)`，任务即进 broker 由 worker 跑。

## 停用 / 删除

- **临时停用**：`QUEUE_ENABLED=False`（enqueue 自动回退 eager）。
- **彻底移除**：删除 `app/core/queue/` 目录、`requirements-queue.txt`，并删掉 `Settings` 里的
  `QUEUE_ENABLED` 字段即可。因 core 不依赖本模块，删除后**无需改动 main.py 或任何核心代码**
  （只需删掉曾经 `import app.core.queue` 的那些业务调用点）。

## 降级与不变量

- **任务必须登记**：新任务要加入 `tasks.TASKS`，否则 `enqueue` 抛 `ValueError`
  （防止投出 worker 无法执行的 job）。
- **任务幂等可重试**：worker 崩溃可能重投，任务逻辑要可安全重复执行。
- **worker 自管 DB 会话**：worker 进程没有请求级 `Depends(get_db)`，任务内用
  `async with get_session() as db:`（见 `app/database.py`）。
- **eager ≠ 真实环境**：本地默认 eager 跑通，不代表真实 broker 下的并发/重试行为一致；
  上线前用真实 Redis + worker 验证。

## 测试

`tests/core/test_queue.py`：覆盖 eager 降级（禁用 / 启用但无 broker）与"未登记任务被拒"。
不依赖真实 Redis / arq broker。真实投递→消费链路需起 Redis + worker 手测。

## 扩展指引

- **加任务**：在 `tasks.py` 写 `async def`，登记到 `TASKS`；worker 与 enqueue 自动识别。
- **定时任务（cron）**：在 `WorkerSettings` 加 `cron_jobs = [cron(my_task, hour=3)]`（`from arq import cron`）。
- **重试/超时**：在 `WorkerSettings` 配 `max_tries` / `job_timeout` / `keep_result` 等。
- **独立 broker DB**：如需与限流/缓存隔离，可后续加 `QUEUE_REDIS_URL` 配置项，默认回退 `REDIS_URL`。
