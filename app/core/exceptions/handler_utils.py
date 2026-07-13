"""异常处理器共用工具：请求上下文、DB 落库、安全 JSON 响应。"""

from __future__ import annotations

from typing import Dict, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.loguru_logger import get_logger
from app.database import get_session

logger = get_logger("exception_handler")


def build_request_context_dict(request: Request) -> dict:
    """构造写日志库用的请求上下文字典（多处处理器共用）。"""
    return {
        "request_id": getattr(request.state, "request_id", None),
        "user_id": getattr(request.state, "user_id", None),
        "method": request.method,
        "endpoint": f"{request.method} {request.url.path}",
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


async def record_exception_to_db(
    request: Request,
    record_fn,
    *args,
    log_label: str = "异常",
    traceback_id: Optional[str] = None,
) -> None:
    """把异常/验证错误写入 DB（best-effort）。

    DB 记录失败不影响响应，只记日志。仅在业务异常处理器（健康路径）使用，
    兜底 500 处理器不应调用此函数。
    """
    try:
        async with get_session() as db:
            from app.services.exception_service import ExceptionService

            exception_service = ExceptionService(db)
            await record_fn(
                exception_service,
                request_context=build_request_context_dict(request),
                *args,
            )
    except Exception as db_error:
        logger.error(
            f"记录{log_label}到数据库失败: {type(db_error).__name__}: {str(db_error)}",
            traceback_id=traceback_id,
        )


def safe_json_response(
    status_code: int,
    response_model,
    fallback_body: dict,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    """优先用 response_model 序列化；失败时回退到 fallback_body。

    headers 用于透传异常携带的自定义响应头（如 OAuth2 的 WWW-Authenticate）。
    """
    try:
        return JSONResponse(
            status_code=status_code,
            content=response_model.model_dump(),
            headers=headers,
        )
    except Exception:
        return JSONResponse(
            status_code=status_code, content=fallback_body, headers=headers
        )
