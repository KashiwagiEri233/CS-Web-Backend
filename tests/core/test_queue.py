"""异步任务队列（可选模块）测试。只验证 eager 降级与注册校验，不依赖真实 Redis / arq broker。"""

import pytest

import app.core.queue.client as qc
from app.core.config import settings
from app.core.queue import enqueue


async def test_enqueue_eager_runs_inline_when_disabled(monkeypatch):
    """QUEUE_ENABLED=False 时，enqueue 应就地执行任务并返回 None（eager 降级）。"""
    ran = {"called": False, "args": None, "eager": None}

    async def spy_task(ctx, x, y=0):
        ran["called"] = True
        ran["args"] = (x, y)
        ran["eager"] = ctx.get("eager")
        return x + y

    # 把临时任务登记进合法集合（生产由 tasks.TASKS 静态登记）
    monkeypatch.setattr(qc, "_TASK_NAMES", qc._TASK_NAMES | {"spy_task"})
    monkeypatch.setattr(settings, "QUEUE_ENABLED", False)

    job_id = await enqueue(spy_task, 3, y=4)

    assert job_id is None              # eager 模式不产生 job_id
    assert ran["called"] is True       # 就地执行了
    assert ran["args"] == (3, 4)       # 参数透传正确
    assert ran["eager"] is True        # ctx 标记 eager


async def test_enqueue_eager_when_enabled_but_no_broker(monkeypatch):
    """QUEUE_ENABLED=True 但未配 REDIS_URL 时，仍降级 eager（不崩、不丢任务）。"""
    ran = {"called": False}

    async def spy_task(ctx):
        ran["called"] = True

    monkeypatch.setattr(qc, "_TASK_NAMES", qc._TASK_NAMES | {"spy_task"})
    monkeypatch.setattr(settings, "QUEUE_ENABLED", True)
    monkeypatch.setattr(settings, "REDIS_URL", None)
    # 重置连接池惰性状态，确保走 _get_pool 的"未配 broker"分支
    monkeypatch.setattr(qc, "_pool", None)
    monkeypatch.setattr(qc, "_pool_initialized", False)

    job_id = await enqueue(spy_task)

    assert job_id is None
    assert ran["called"] is True


async def test_enqueue_rejects_unregistered_task():
    """未登记到 TASKS 的任务应被拒绝投递（防止 worker 收到无法执行的 job）。"""

    async def ghost_task(ctx):
        ...

    with pytest.raises(ValueError, match="未在.*TASKS 注册"):
        await enqueue(ghost_task)
