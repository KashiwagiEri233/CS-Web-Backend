"""请求体大小限制中间件（纯 ASGI）。

没有这层防护时，任何人都可以 POST 一个几百 MB 的 JSON：body 会被完整读进内存
再交给 pydantic 校验，单个请求就能把进程打爆——uvicorn 本身不限制请求体大小。

两道检查缺一不可：
1. ``Content-Length`` 声明超限 -> 立即拒绝，一个字节都不读（最省资源，覆盖绝大多数情况）。
2. 分块传输（``Transfer-Encoding: chunked``）没有 Content-Length，只能边收边累计，
   超限时中断。否则声明为 chunked 就能绕过第 1 条。
"""

from typing import Any, Awaitable, Callable, MutableMapping

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

from app.core.exceptions import ErrorCode

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

# 没有请求体的方法直接放行，省掉 header 解析
_BODYLESS_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "DELETE"})


class BodySizeLimitMiddleware:
    """拒绝超过 ``max_bytes`` 的请求体，返回 413。

    Args:
        app: 下游 ASGI 应用
        max_bytes: 允许的最大请求体字节数
    """

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in _BODYLESS_METHODS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        declared = headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                # Content-Length 非法：交给下游/服务器按协议错误处理，不在此臆断
                pass

        # 分块传输没有 Content-Length，只能在读取过程中累计计数
        received = 0
        too_large = False

        async def counting_receive() -> MutableMapping[str, Any]:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    # 截断请求体并标记结束，避免下游继续等待后续分块
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        # 下游读完（或读爆）body 后才知道是否超限；超限时下游通常会因 body 不完整
        # 而抛校验错误，这里用 _rejected 标志把响应改写为语义正确的 413。
        async def guarded_send(message: MutableMapping[str, Any]) -> None:
            if too_large and message["type"] == "http.response.start":
                raise _BodyTooLarge()
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _BodyTooLarge:
            await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={
                "success": False,
                "error_code": ErrorCode.Request.REQUEST_BODY_TOO_LARGE,
                "message": f"请求体过大，最大允许 {self.max_bytes} 字节。",
                "status_code": status.HTTP_413_CONTENT_TOO_LARGE,
            },
        )
        await response(scope, receive, send)


class _BodyTooLarge(Exception):
    """内部信号：分块请求体超限，需把响应改写为 413。不会逃逸出本模块。"""
