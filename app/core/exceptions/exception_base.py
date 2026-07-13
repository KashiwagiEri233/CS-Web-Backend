"""应用程序基础异常类。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4


class BaseAppException(Exception):
    """应用程序基础异常类。

    所有自定义异常的基础类，提供统一的错误处理机制。
    """

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        """初始化基础异常。

        Args:
            message: 错误消息。
            error_code: 自定义错误代码。
            status_code: HTTP 状态码。
            details: 错误详细信息。
            context: 错误上下文信息。
            cause: 原始异常对象。
            headers: 附加到 HTTP 响应的自定义头（如 OAuth2 的 WWW-Authenticate）。
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.status_code = status_code
        self.details = details or {}
        self.context = context or {}
        self.cause = cause
        self.headers = headers
        self.traceback_id = str(uuid4())
        self.timestamp: Optional[datetime] = None  # 将在处理器中设置

    def to_dict(self) -> Dict[str, Any]:
        """将异常转换为字典格式"""
        result = {
            "error_code": self.error_code,
            "message": self.message,
            "status_code": self.status_code,
            "traceback_id": self.traceback_id,
        }

        if self.details:
            result["details"] = self.details

        if self.context:
            result["context"] = self.context

        if self.cause:
            result["cause"] = str(self.cause)

        if self.timestamp:
            result["timestamp"] = self.timestamp.isoformat()

        return result

    def __str__(self) -> str:
        """字符串表示"""
        return f"[{self.error_code}] {self.message}"

    def __repr__(self) -> str:
        """调试表示"""
        return (
            f"{self.__class__.__name__}(message='{self.message}', "
            f"error_code='{self.error_code}', status_code={self.status_code})"
        )
