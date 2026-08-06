"""异常子系统核心单测。

不依赖 DB 的部分：ExceptionLogger 的 log_exception/log_validation_error 行为。
依赖 DB 的部分：record_exception 落库 + 查询（无 DB 时 skip）。
"""

from app.core.exceptions import (
    BusinessException,
    NotFoundException,
)
from app.core.exceptions.exception_logging import ExceptionLogger
from app.core.exceptions.error_builders import _serialize_validation_errors
from tests.conftest import integration_db_unavailable

# ------------------------------------------------------------------ ExceptionLogger


def test_log_exception_for_base_app_exception():
    """业务异常：log_record 应包含 error_code/status_code/traceback_id。"""
    logger = ExceptionLogger()
    exc = NotFoundException(resource_type="user", resource_id=999)
    record = logger.log_exception(exc)

    assert record["exception_type"] == "NotFoundException"
    assert record["error_code"] == "RESOURCE_NOT_FOUND"
    assert record["status_code"] == 404
    assert record["traceback_id"]  # 非空
    assert "traceback" in record


def test_log_exception_for_plain_exception():
    """普通异常：log_record 应有 traceback_id（现场生成），无 error_code。"""
    logger = ExceptionLogger()
    exc = RuntimeError("something broke")
    record = logger.log_exception(exc)

    assert record["exception_type"] == "RuntimeError"
    assert record["exception_message"] == "something broke"
    assert record["traceback_id"]
    assert "error_code" not in record or record.get("error_code") is None


def test_log_exception_with_request_context():
    """请求上下文应被附加到 log_record。"""
    logger = ExceptionLogger()
    exc = BusinessException(message="test")
    ctx = {"request_id": "req-123", "user_id": 42, "endpoint": "GET /test"}
    record = logger.log_exception(exc, request_context=ctx)

    assert record["request_context"]["request_id"] == "req-123"
    assert record["request_context"]["user_id"] == 42


def test_log_validation_error():
    """验证错误：log_record 应含 errors 列表。"""
    logger = ExceptionLogger()
    errors = [{"loc": ["body", "name"], "msg": "field required"}]
    record = logger.log_validation_error(errors=errors)

    assert record["error_type"] == "validation_error"
    assert len(record["errors"]) == 1


def test_validation_error_serialization_removes_raw_input():
    errors = [
        {
            "type": "value_error",
            "loc": ("body", "password"),
            "input": "PlaintextPassword1!",
            "ctx": {"error": ValueError("invalid")},
        }
    ]
    safe = _serialize_validation_errors(errors)

    assert "input" not in safe[0]
    assert isinstance(safe[0]["ctx"]["error"], str)


def test_log_exception_traceback_id_from_base_app_exception():
    """BaseAppException 自带 traceback_id 时应优先使用。"""
    logger = ExceptionLogger()
    exc = BusinessException(message="custom")
    original_tid = exc.traceback_id
    record = logger.log_exception(exc)

    assert record["traceback_id"] == original_tid


# ------------------------------------------------------------------ 统一响应格式


def test_base_exception_to_dict_has_required_fields():
    """BaseAppException.to_dict() 应包含统一响应需要的字段。"""
    exc = BusinessException(message="test", details={"key": "value"})
    d = exc.to_dict()

    assert "error_code" in d
    assert "message" in d
    assert "status_code" in d
    assert "traceback_id" in d
    assert d["status_code"] == 400


# ------------------------------------------------------------------ DB 集成（无 DB 时 skip）


async def _db_available() -> bool:
    try:
        from app.database import get_session
        from sqlalchemy import text

        async with get_session() as db:
            await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def test_record_exception_to_db():
    """record_exception 应成功写入 DB 并返回 ExceptionLog。"""
    if not await _db_available():
        integration_db_unavailable("数据库不可用，无法验证异常日志落库")

    from app.database import get_session
    from app.services.exception_service import ExceptionService
    from sqlalchemy import text
    import uuid

    from tests._alembic_helpers import upgrade_schema_to_head

    # 确保表存在（Alembic only）
    await upgrade_schema_to_head()

    ctx = {
        "method": "GET",
        "endpoint": "GET /test",
        "request_id": "test-req-" + uuid.uuid4().hex[:8],
        "ip_address": "127.0.0.1",
        "user_agent": "test",
    }

    async with get_session() as db:
        svc = ExceptionService(db)
        exc = BusinessException(message="db test error")
        log = await svc.record_exception(exc, request_context=ctx)
        await db.commit()

        assert log.id is not None
        assert log.exception_type == "BusinessException"
        assert log.status_code == 400
        assert log.endpoint == "GET /test"
        assert log.is_resolved is False

        # 清理
        await db.execute(
            text("DELETE FROM exception_logs WHERE id = :i"), {"i": log.id}
        )
        await db.commit()
