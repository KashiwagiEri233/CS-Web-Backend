"""
异常响应模型
定义统一的错误响应格式和数据结构
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict


class ErrorContext(BaseModel):
    """错误上下文信息"""
    request_id: Optional[str] = Field(None, description="请求唯一ID")
    user_id: Optional[Union[str, int]] = Field(None, description="用户ID")
    ip_address: Optional[str] = Field(None, description="客户端IP地址")
    user_agent: Optional[str] = Field(None, description="用户代理")
    endpoint: Optional[str] = Field(None, description="请求端点")
    method: Optional[str] = Field(None, description="HTTP方法")
    timestamp: Optional[datetime] = Field(None, description="错误发生时间")
    
    model_config = ConfigDict(
        from_attributes=True
    )
    
    def model_dump(self, **kwargs):
        """重写 model_dump 方法以正确处理 datetime 对象"""
        data = super().model_dump(**kwargs)
        if 'timestamp' in data and data['timestamp'] is not None:
            if isinstance(data['timestamp'], datetime):
                data['timestamp'] = data['timestamp'].isoformat()
        return data


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
                "code": "REQUIRED_FIELD"
            }
        }
    )


class ErrorResponse(BaseModel):
    """统一错误响应格式"""
    success: bool = Field(False, description="请求是否成功")
    error_code: str = Field(..., description="错误代码")
    message: str = Field(..., description="错误消息")
    status_code: int = Field(..., description="HTTP状态码")
    details: Optional[Dict[str, Any]] = Field(None, description="错误详细信息")
    validation_errors: Optional[List[ErrorDetail]] = Field(None, description="验证错误列表")
    context: Optional[ErrorContext] = Field(None, description="错误上下文")
    traceback_id: Optional[str] = Field(None, description="异常跟踪ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="响应时间")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error_code": "VALIDATION_FAILED",
                "message": "数据验证失败",
                "status_code": 422,
                "details": {
                    "username": "用户名已存在",
                    "email": "邮箱格式不正确"
                },
                "validation_errors": [
                    {
                        "field": "username",
                        "message": "用户名已存在",
                        "code": "USERNAME_EXISTS"
                    }
                ],
                "context": {
                    "request_id": "req_123456",
                    "user_id": "user_789",
                    "endpoint": "/api/v1/users",
                    "method": "POST"
                },
                "traceback_id": "trace_abc123",
                "timestamp": "2023-01-01T12:00:00.000Z"
            }
        }
    )
    
    def model_dump(self, **kwargs):
        """重写 model_dump 方法以正确处理 datetime 对象"""
        data = super().model_dump(**kwargs)
        if 'timestamp' in data and data['timestamp'] is not None:
            if isinstance(data['timestamp'], datetime):
                data['timestamp'] = data['timestamp'].isoformat()
        return data


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
                        "code": "REQUIRED_FIELD"
                    },
                    {
                        "field": "email",
                        "message": "邮箱格式不正确",
                        "code": "INVALID_FORMAT"
                    }
                ],
                "traceback_id": "trace_abc123",
                "timestamp": "2023-01-01T12:00:00.000Z"
            }
        }
    )


class AuthenticationErrorResponse(ErrorResponse):
    """认证错误响应"""
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error_code": "INVALID_CREDENTIALS",
                "message": "用户名或密码错误",
                "status_code": 401,
                "traceback_id": "trace_abc123",
                "timestamp": "2023-01-01T12:00:00.000Z"
            }
        }
    )


class AuthorizationErrorResponse(ErrorResponse):
    """授权错误响应"""
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error_code": "PERMISSION_DENIED",
                "message": "权限不足",
                "status_code": 403,
                "details": {
                    "required_permissions": ["user:create", "user:read"]
                },
                "traceback_id": "trace_abc123",
                "timestamp": "2023-01-01T12:00:00.000Z"
            }
        }
    )


class NotFoundErrorResponse(ErrorResponse):
    """资源未找到错误响应"""
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error_code": "RESOURCE_NOT_FOUND",
                "message": "用户 (ID: 123) 未找到",
                "status_code": 404,
                "details": {
                    "resource_type": "用户",
                    "resource_id": "123"
                },
                "traceback_id": "trace_abc123",
                "timestamp": "2023-01-01T12:00:00.000Z"
            }
        }
    )


class ConflictErrorResponse(ErrorResponse):
    """冲突错误响应"""
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error_code": "USER_ALREADY_EXISTS",
                "message": "用户名 'john_doe' 已存在",
                "status_code": 409,
                "details": {
                    "username": "john_doe"
                },
                "traceback_id": "trace_abc123",
                "timestamp": "2023-01-01T12:00:00.000Z"
            }
        }
    )


class RateLimitErrorResponse(ErrorResponse):
    """限流错误响应"""
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": "请求频率超限",
                "status_code": 429,
                "details": {
                    "limit": 100,
                    "window_seconds": 3600
                },
                "traceback_id": "trace_abc123",
                "timestamp": "2023-01-01T12:00:00.000Z"
            }
        }
    )


class ServerErrorResponse(ErrorResponse):
    """服务器错误响应"""
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "内部服务器错误",
                "status_code": 500,
                "traceback_id": "trace_abc123",
                "timestamp": "2023-01-01T12:00:00.000Z"
            }
        }
    )


class DatabaseErrorResponse(ErrorResponse):
    """数据库错误响应"""
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error_code": "DATABASE_ERROR",
                "message": "数据库操作失败: INSERT on users",
                "status_code": 500,
                "details": {
                    "operation": "INSERT",
                    "table": "users"
                },
                "traceback_id": "trace_abc123",
                "timestamp": "2023-01-01T12:00:00.000Z"
            }
        }
    )


class ExternalServiceErrorResponse(ErrorResponse):
    """外部服务错误响应"""
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error_code": "EXTERNAL_SERVICE_ERROR",
                "message": "外部服务调用失败: payment_service",
                "status_code": 502,
                "details": {
                    "service_name": "payment_service",
                    "endpoint": "https://api.payment.com/charge"
                },
                "traceback_id": "trace_abc123",
                "timestamp": "2023-01-01T12:00:00.000Z"
            }
        }
    )