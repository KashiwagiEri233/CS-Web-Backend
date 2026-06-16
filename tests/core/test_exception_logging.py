"""异常落库链路的回归测试。

针对两个曾经的偶发告警：
1. loguru 误用 exc_info= 导致含 JSON 的消息触发 .format() -> KeyError；
2. log_exception 仅对 BaseAppException 设置 traceback_id，普通异常入库时 NOT NULL 失败。
不依赖数据库。
"""

from fastapi import HTTPException

from app.core.loguru_logger import get_logger
from app.core.exceptions.exception_logging import ExceptionLogger
from app.core.exceptions.base_exceptions import NotFoundException


def test_error_log_with_json_kwargs_and_exc_info_does_not_raise():
    """含 dict 参数 + exc_info 的错误日志不应抛 KeyError（曾因 loguru .format() 失败）。"""
    log = get_logger("regression_logging")
    try:
        raise ValueError("boom")
    except ValueError:
        # context 是 dict，会被 json.dumps 成含 {} 的字符串；旧实现 + exc_info= 会 KeyError
        log.error(
            "未处理的异常",
            context={"request_id": "abc-123", "endpoint": "GET /x"},
            exc_info=True,
        )
    # 执行到此处未抛异常即通过


def test_log_exception_always_sets_traceback_id_for_plain_exception():
    rec = ExceptionLogger().log_exception(RuntimeError("x"))
    assert rec.get("traceback_id")  # 非 None 非空


def test_log_exception_uses_app_exception_traceback_id():
    exc = NotFoundException(resource_type="thing", resource_id="1")
    rec = ExceptionLogger().log_exception(exc)
    assert rec.get("traceback_id") == exc.traceback_id


def test_log_exception_captures_http_exception_status_code():
    rec = ExceptionLogger().log_exception(HTTPException(status_code=403, detail="x"))
    assert rec.get("status_code") == 403
    assert rec.get("error_code") == "HTTP_403"
