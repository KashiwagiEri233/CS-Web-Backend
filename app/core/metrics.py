"""Prometheus 指标（ER-06 / AL-5）：提供可被 scraper 拉取的标准 ``/metrics`` 端点。

与既有内存版 ``MetricsMiddleware`` / ``/metrics/json`` 并存：
- ``/metrics/json`` 服务于内部运维/安全视图（进程内计数，零依赖）；
- ``/metrics``（本模块）输出 Prometheus 文本格式，供 Prometheus/OTel scraper 拉取，
  支撑告警最小集（错误率 / 延迟 / 饱和度）的真实数据。

指标（RED + 进程级）：
- ``http_requests_total{method,path,status}``        错误率来源
- ``http_request_duration_seconds{method,path}``     延迟（直方图）
- ``http_requests_in_progress``                      饱和度
- ``process_*`` / ``python_*``                        由 prometheus_client 默认收集器自动提供
"""

from __future__ import annotations

import re
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "path", "status"],
)
_REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
)
_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "In-progress HTTP requests.",
)

# 归一化路径，避免高基数爆炸：/users/123 -> /users/{id}
_PATH_ID_RE = re.compile(r"/(?P<id>\d+)(?=/|$)")


def _normalize_path(path: str) -> str:
    """把路径中的数值段替换为 {id}，控制标签基数。"""
    return _PATH_ID_RE.sub("/{id}", path)


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """为每个请求累加 Prometheus 指标（错误率 / 延迟 / 饱和度）。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        _REQUESTS_IN_PROGRESS.inc()
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            _REQUESTS_IN_PROGRESS.dec()
        path = _normalize_path(request.url.path)
        duration = time.perf_counter() - start
        _REQUEST_LATENCY.labels(request.method, path).observe(duration)
        _REQUEST_COUNT.labels(request.method, path, str(response.status_code)).inc()
        return response


def metrics_response() -> Response:
    """``/metrics`` 端点处理器：返回 Prometheus 文本格式。"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
