"""启动 / 关闭任务注册表（lifecycle registry）测试。

不依赖真实 DB / Redis / 网络：仅验证注册表的排序、critical 失败传播、重名报错、
关闭降序执行等纯逻辑。通过 monkeypatch 临时接管全局注册表，避免污染项目模块
（database / rbac_init / redis_client / observability / main）已登记的真实任务。
"""

import pytest

from app.core.lifecycle import registry as lc


def _fresh_registries(monkeypatch):
    """替换全局注册表为空的副本，并返回它供断言；测试结束自动恢复。

    项目各模块在 import 时已向 registry._STARTUP_TASKS 登记真实任务，这里用空列表
    替换以隔离被测逻辑，避免真实任务（如建库）被 run_startup 误触发。
    """
    startup, shutdown = [], []
    monkeypatch.setattr(lc, "_STARTUP_TASKS", startup)
    monkeypatch.setattr(lc, "_SHUTDOWN_TASKS", shutdown)
    monkeypatch.setattr(lc, "_STARTUP_NAMES", set())
    monkeypatch.setattr(lc, "_SHUTDOWN_NAMES", set())
    return startup, shutdown


# --------------------------- 注册与排序 ---------------------------


async def test_startup_executes_in_priority_ascending_order(monkeypatch):
    _fresh_registries(monkeypatch)
    order = []

    @lc.register_startup("c", priority=30, critical=False)
    async def _c():
        order.append("c")

    @lc.register_startup("a", priority=10, critical=False)
    async def _a():
        order.append("a")

    @lc.register_startup("b", priority=20, critical=False)
    async def _b():
        order.append("b")

    await lc.run_startup()
    assert order == ["a", "b", "c"]


async def test_shutdown_executes_in_priority_descending_order(monkeypatch):
    _fresh_registries(monkeypatch)
    order = []

    @lc.register_shutdown("a", priority=10)
    async def _a():
        order.append("a")

    @lc.register_shutdown("b", priority=20)
    async def _b():
        order.append("b")

    @lc.register_shutdown("c", priority=30)
    async def _c():
        order.append("c")

    await lc.run_shutdown()
    # 降序：后启动的先关
    assert order == ["c", "b", "a"]


# --------------------------- critical 失败传播 ---------------------------


async def test_critical_failure_aborts_startup_and_skips_remaining(monkeypatch):
    _fresh_registries(monkeypatch)
    called = []

    @lc.register_startup("ok_before", priority=10, critical=False)
    async def _ok_before():
        called.append("before")

    @lc.register_startup("boom", priority=20, critical=True)
    async def _boom():
        called.append("boom")
        raise RuntimeError("db down")

    @lc.register_startup("after", priority=30, critical=False)
    async def _after():
        called.append("after")

    with pytest.raises(RuntimeError, match="db down"):
        await lc.run_startup()
    # critical 失败 → 中止，后续任务不执行
    assert called == ["before", "boom"]


async def test_non_critical_failure_does_not_abort(monkeypatch):
    _fresh_registries(monkeypatch)
    called = []

    @lc.register_startup("fail", priority=10, critical=False)
    async def _fail():
        called.append("fail")
        raise RuntimeError("redis down")

    @lc.register_startup("after", priority=20, critical=False)
    async def _after():
        called.append("after")

    # 非关键失败不抛
    await lc.run_startup()
    assert called == ["fail", "after"]


async def test_shutdown_swallows_all_exceptions(monkeypatch):
    """关闭阶段任何任务失败都只记日志，绝不向外抛。"""
    _fresh_registries(monkeypatch)
    called = []

    @lc.register_shutdown("fail", priority=20)
    async def _fail():
        called.append("fail")
        raise RuntimeError("flush error")

    @lc.register_shutdown("ok", priority=10)
    async def _ok():
        called.append("ok")

    await lc.run_shutdown()  # 不应抛
    # 降序：priority=20 先执行（失败），priority=10 后执行（仍被调用）
    assert called == ["fail", "ok"]


# --------------------------- 重名保护 ---------------------------


def test_duplicate_startup_name_raises(monkeypatch):
    _fresh_registries(monkeypatch)

    @lc.register_startup("dup", priority=10, critical=False)
    async def _first():
        pass

    with pytest.raises(ValueError, match="已注册"):

        @lc.register_startup("dup", priority=20, critical=False)
        async def _second():  # pragma: no cover - 装饰器内即抛
            pass


def test_duplicate_shutdown_name_raises(monkeypatch):
    _fresh_registries(monkeypatch)

    @lc.register_shutdown("dup", priority=10)
    async def _first():
        pass

    with pytest.raises(ValueError, match="已注册"):

        @lc.register_shutdown("dup", priority=20)
        async def _second():  # pragma: no cover - 装饰器内即抛
            pass


# --------------------------- 装饰器返回原函数 ---------------------------


def test_decorator_returns_original_function(monkeypatch):
    """装饰器不应吞掉被装饰函数（注册表只登记引用，原函数仍可直接调用）。"""
    import asyncio

    _fresh_registries(monkeypatch)

    @lc.register_startup("x", priority=10, critical=False)
    async def my_func():
        return 42

    # 装饰器返回的是原协程函数对象本身（仍可 await 调用），而非被替换
    assert asyncio.iscoroutinefunction(my_func)

    async def _call():
        return await my_func()

    assert asyncio.run(_call()) == 42
