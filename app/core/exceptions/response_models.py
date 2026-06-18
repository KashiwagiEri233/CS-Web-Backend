"""
异常响应模型
定义统一的错误响应格式和数据结构
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict

from app.core.timezone import now_utc
from app.schemas.base import TZModel


class ErrorContext(TZModel):
    """错误上下文信息

    继承 TZModel：timestamp 等 datetime 字段由基类序列化器统一转 settings.TIMEZONE
    并输出 ISO 字符串（兼容 JSONResponse 的 python 模式 model_dump），无需再手写 model_dump。
    """

    request_id: Optional[str] = Field(None, description="请求唯一ID")
    user_id: Optional[Union[str, int]] = Field(None, description="用户ID")
    ip_address: Optional[str] = Field(None, description="客户端IP地址")
    user_agent: Optional[str] = Field(None, description="用户代理")
    endpoint: Optional[str] = Field(None, description="请求端点")
    method: Optional[str] = Field(None, description="HTTP方法")
    timestamp: Optional[datetime] = Field(None, description="错误发生时间")


class ErrorDetail(BaseModel):
    """错误详细信息"""

    field: Optional[str] = Field(None, description="错误字段")
    message: str = Field(..., description="错误消息")
    code: Optional[str] = Field(None, description="错误代码")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "field": "username",
                "message": "用户名不能为空",
                "code": "REQUIRED_FIELD",
            }
        }
    )


class ErrorResponse(TZModel):
    """统一错误响应格式

    继承 TZModel：timestamp 由基类序列化器统一转本地时区并输出 ISO 字符串。
    """

    success: bool = Field(False, description="请求是否成功")
    error_code: str = Field(..., description="错误代码")
    message: str = Field(..., description="错误消息")
    status_code: int = Field(..., description="HTTP状态码")
    details: Optional[Dict[str, Any]] = Field(None, description="错误详细信息")
    validation_errors: Optional[List[ErrorDetail]] = Field(
        None, description="验证错误列表"
    )
    context: Optional[ErrorContext] = Field(None, description="错误上下文")
    traceback_id: Optional[str] = Field(None, description="异常跟踪ID")
    timestamp: datetime = Field(
        default_factory=now_utc, description="响应时间"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error_code": "VALIDATION_FAILED",
                "message": "数据验证失败",
                "status_code": 422,
                "details": {"username": "用户名已存在", "email": "邮箱格式不正确"},
                "validation_errors": [
                    {
                        "field": "username",
                        "message": "用户名已存在",
                        "code": "USERNAME_EXISTS",
                    }
                ],
                "context": {
                    "request_id": "req_123456",
                    "user_id": "user_789",
                    "endpoint": "/api/v1/users",
                    "method": "POST",
                },
                "traceback_id": "trace_abc123",
                "timestamp": "2023-01-01T12:00:00.000Z",
            }
        }
    )

class ValidationErrorResponse(ErrorResponse):
    """验证错误响应"""

    validation_errors: List[ErrorDetail] = Field(..., description="验证错误列表")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error_code": "VALIDATION_FAILED",
                "message": "数据验证失败",
                "status_code": 422,
                "validation_errors": [
                    {
                        "field": "username",
                        "message": "用户名不能为空",
                        "code": "REQUIRED_FIELD",
                    },
                    {
                        "field": "email",
                        "message": "邮箱格式不正确",
                        "code": "INVALID_FORMAT",
                    },
                ],
                "traceback_id": "trace_abc123",
                "timestamp": "2023-01-01T12:00:00.000Z",
            }
        }
    )



