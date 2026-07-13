"""结构化日志上下文回归测试。"""

from loguru import logger as loguru_logger

from app.core.loguru_logger import (
    clear_logging_context,
    get_logger,
    set_logging_context,
)


def test_adapter_binds_context_and_fields_into_loguru_extra():
    records = []
    sink_id = loguru_logger.add(lambda message: records.append(message.record))
    try:
        set_logging_context(request_id="req-structured")
        get_logger("structured_test").info("done", status_code=200)
    finally:
        clear_logging_context()
        loguru_logger.remove(sink_id)

    record = records[-1]
    assert record["extra"]["request_id"] == "req-structured"
    assert record["extra"]["status_code"] == 200
