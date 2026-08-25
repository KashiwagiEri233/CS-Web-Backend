"""真实 Redis + arq worker 的投递、消费和重试集成测试。"""

from __future__ import annotations

import os

import pytest

# arq 已在主依赖（pyproject.toml）；importorskip 仅作防御，缺失时整模块 skip 而非收集报错
arq = pytest.importorskip("arq")
from arq import Retry, Worker, func as arq_func  # noqa: E402
from arq.jobs import Job  # noqa: E402
import app.core.queue.client as queue_client  # noqa: E402
from app.core.config import settings  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.queue_integration]


async def test_enqueue_worker_consumes_and_retries(
    integration_redis_client, monkeypatch
):
    attempts = {"count": 0}

    async def integration_retry_task(ctx, value: int) -> int:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise Retry(defer=0)
        return value + 1

    redis_url = os.environ.get("TEST_REDIS_URL") or os.environ["REDIS_URL"]
    monkeypatch.setattr(settings, "REDIS_URL", redis_url)
    # 注：_QUEUE_ENABLED 在模块 import 时求值（_read_queue_enabled()），
    # 必须 patch 常量本身而非函数，否则 enqueue 走 eager 路径、Retry 直接逃逸。
    monkeypatch.setattr(queue_client, "_QUEUE_ENABLED", True)
    monkeypatch.setattr(queue_client, "_pool", None)
    monkeypatch.setattr(queue_client, "_pool_initialized", False)
    monkeypatch.setattr(
        queue_client,
        "_TASK_NAMES",
        queue_client._TASK_NAMES | {integration_retry_task.__name__},
    )

    await integration_redis_client.flushdb()
    try:
        job_id = await queue_client.enqueue(integration_retry_task, 41)
        assert job_id

        pool = await queue_client._get_pool()
        assert pool is not None
        # 注：arq Function.name 默认取 __qualname__（闭包含 <locals> 前缀），
        # 与 enqueue 投递的 __name__ 不匹配会报 "function not found"；
        # 用 arq_func 包装并显式 name 对齐。
        worker = Worker(
            [arq_func(integration_retry_task, name=integration_retry_task.__name__)],
            redis_pool=pool,
            burst=True,
            handle_signals=False,
            poll_delay=0.05,
            max_burst_jobs=3,
        )
        await worker.async_run()

        result = await Job(job_id, pool).result(timeout=2)
        assert result == 42
        assert attempts["count"] == 2
    finally:
        await queue_client.close_queue_pool()
        await integration_redis_client.flushdb()
