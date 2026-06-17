"""指标中间件测试：守住 /metrics/json 端点依赖的实例引用机制（无需 DB/Redis）。

背景：Starlette 的 app.user_middleware 只存 Middleware 规格（类+参数），不暴露实例；
旧端点用 `middleware.instance` 遍历会 AttributeError 直接 500。现改为实例化时登记
MetricsMiddleware._instance，本测试守住该机制不被回退。
"""

from app.middleware.monitoring import MetricsMiddleware


async def _dummy_app(scope, receive, send):  # 占位 ASGI app
    ...


def test_metrics_middleware_registers_instance():
    mw = MetricsMiddleware(_dummy_app)
    assert MetricsMiddleware._instance is mw


def test_get_metrics_shape():
    mw = MetricsMiddleware(_dummy_app)
    m = mw.get_metrics()
    assert {"requests", "performance", "error_rate", "uptime_seconds"}.issubset(m)
    assert {"total", "errors", "by_status", "by_method", "by_path"}.issubset(m["requests"])
