"""ExceptionService 内部逻辑单元测试（不依赖数据库）。

聚焦 #16 修复：_determine_severity 的严重度语义。
"""

from app.services.exception_service import ExceptionService


def test_determine_severity_5xx_is_critical():
    assert ExceptionService._determine_severity(Exception(), 500) == "critical"
    assert ExceptionService._determine_severity(Exception(), 503) == "critical"


def test_determine_severity_4xx_is_medium():
    assert ExceptionService._determine_severity(Exception(), 400) == "medium"
    assert ExceptionService._determine_severity(Exception(), 404) == "medium"
    assert ExceptionService._determine_severity(Exception(), 422) == "medium"


def test_determine_severity_other_is_low():
    """无状态码或 <400 的异常严重度应为 low（低于 4xx 的 medium）。

    这是 #16 修复点：原实现错误地返回 "high"（比 4xx 还严重），语义反转。
    """
    assert ExceptionService._determine_severity(Exception(), None) == "low"
    assert ExceptionService._determine_severity(Exception(), 302) == "low"
    assert ExceptionService._determine_severity(Exception(), 200) == "low"


def test_determine_severity_ordering_is_monotonic():
    """严重度应随状态码升高而升高：low < medium < critical。"""
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    low = ExceptionService._determine_severity(Exception(), None)
    medium = ExceptionService._determine_severity(Exception(), 404)
    critical = ExceptionService._determine_severity(Exception(), 500)
    assert order[low] < order[medium] < order[critical]
