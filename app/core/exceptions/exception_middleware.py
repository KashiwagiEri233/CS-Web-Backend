"""异常处理中间件：捕获中间件层抛出的异常并映射为统一错误响应。"""

from __future__ import annotations

import uuid

from fastapi import Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.loguru_logger import get_logger
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
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        try:
            await self.app(scope, receive, send)
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
                await response_obj(scope, receive, send)
            except Exception as send_exc:
                if type(send_exc).__name__ in _CLIENT_DISCONNECT_NAMES:
                    return
                raise
