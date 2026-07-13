"""异常处理中间件：捕获中间件层抛出的异常并映射为统一错误响应。"""

from __future__ import annotations

import re
import uuid

from fastapi import Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.loguru_logger import (
    get_logger,
    reset_logging_context,
    set_logging_context,
)
from app.core.timezone import now_utc

from .base_exceptions import BaseAppException
from .error_builders import (
    create_app_exception_response,
    create_http_exception_response,
    create_server_error_response,
)
from .error_codes import ErrorCode

logger = get_logger("exception_handler")

_CLIENT_DISCONNECT_NAMES = ("ClientDisconnect", "ClientDisconnected")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


class ExceptionHandlerMiddleware:
    """异常处理中间件。

    中间件层抛出的异常不会经过 ``app.add_exception_handler`` 注册的处理器
    （那些只覆盖路由层），必须在此按类型显式区分，否则 HTTPException 与业务异常
    会被错误地吞成 500。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        supplied_request_id = request.headers.get("x-request-id", "")
        request_id = (
            supplied_request_id
            if _REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else uuid.uuid4().hex
        )
        request.state.request_id = request_id
        context_token = set_logging_context(request_id=request_id)

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers = [
                    header
                    for header in message.get("headers", [])
                    if header[0].lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            # 客户端在响应发送完成前断开：良性事件，不当成服务端 500。
            if type(exc).__name__ in _CLIENT_DISCONNECT_NAMES:
                logger.debug(
                    "客户端提前断开连接，已忽略",
                    endpoint=f"{scope.get('method')} {scope.get('path')}",
                )
                return

            if isinstance(exc, (HTTPException, StarletteHTTPException)):
                response = create_http_exception_response(exc, request)
                extra_headers = getattr(exc, "headers", None)
            elif isinstance(exc, BaseAppException):
                response = create_app_exception_response(exc, request)
                extra_headers = getattr(exc, "headers", None)
            else:
                response = create_server_error_response(exc, request)
                extra_headers = None

            try:
                content = response.model_dump()
                response_obj = JSONResponse(
                    status_code=response.status_code,
                    content=content,
                    headers=extra_headers,
                )
            except Exception:
                content = {
                    "success": False,
                    "error_code": (
                        response.error_code
                        if response
                        else ErrorCode.System.INTERNAL_SERVER_ERROR
                    ),
                    "message": response.message if response else "内部服务器错误",
                    "status_code": response.status_code if response else 500,
                    "traceback_id": response.traceback_id if response else None,
                    "timestamp": now_utc().isoformat(),
                }
                response_obj = JSONResponse(
                    status_code=response.status_code if response else 500,
                    content=content,
                    headers=extra_headers,
                )

            try:
                await response_obj(scope, receive, send_with_request_id)
            except Exception as send_exc:
                if type(send_exc).__name__ in _CLIENT_DISCONNECT_NAMES:
                    return
                raise
        finally:
            reset_logging_context(context_token)
