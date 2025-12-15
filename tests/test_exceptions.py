"""
异常处理系统测试
验证自定义异常类和全局异常处理器的功能
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app.core.exceptions import (
    BaseAppException,
    BusinessException,
    AuthenticationException,
    AuthorizationException,
    ValidationException,
    NotFoundException,
    ConflictException,
    DatabaseException,
    ExternalServiceException,
    RateLimitException,
    setup_exception_handlers,
    ErrorResponse
)
from app.core.exceptions.base_exceptions import (
    UserAlreadyExistsException,
    InvalidCredentialsException,
    UserNotActiveException,
    PermissionDeniedException,
    ResourceNotFoundException
)


class TestBaseException:
    """基础异常测试"""
    
    def test_base_exception_creation(self):
        """测试基础异常创建"""
        exception = BaseAppException(
            message="测试异常",
            error_code="TEST_ERROR",
            status_code=500,
            details={"key": "value"},
            context={"request_id": "123"}
        )
        
        assert exception.message == "测试异常"
        assert exception.error_code == "TEST_ERROR"
        assert exception.status_code == 500
        assert exception.details == {"key": "value"}
        assert exception.context == {"request_id": "123"}
        assert exception.traceback_id is not None
    
    def test_base_exception_to_dict(self):
        """测试基础异常转换为字典"""
        exception = BaseAppException(
            message="测试异常",
            error_code="TEST_ERROR",
            status_code=500,
            details={"key": "value"},
            context={"request_id": "123"}
        )
        
        result = exception.to_dict()
        
        assert result["message"] == "测试异常"
        assert result["error_code"] == "TEST_ERROR"
        assert result["status_code"] == 500
        assert result["details"] == {"key": "value"}
        assert result["context"] == {"request_id": "123"}
        assert "traceback_id" in result
    
    def test_business_exception(self):
        """测试业务异常"""
        exception = BusinessException("业务错误")
        
        assert exception.message == "业务错误"
        assert exception.error_code == "BUSINESS_ERROR"
        assert exception.status_code == 400
    
    def test_authentication_exception(self):
        """测试认证异常"""
        exception = AuthenticationException("认证失败")
        
        assert exception.message == "认证失败"
        assert exception.error_code == "AUTHENTICATION_FAILED"
        assert exception.status_code == 401
    
    def test_authorization_exception(self):
        """测试授权异常"""
        exception = AuthorizationException("权限不足")
        
        assert exception.message == "权限不足"
        assert exception.error_code == "AUTHORIZATION_FAILED"
        assert exception.status_code == 403
    
    def test_validation_exception(self):
        """测试验证异常"""
        exception = ValidationException("验证失败")
        
        assert exception.message == "验证失败"
        assert exception.error_code == "VALIDATION_FAILED"
        assert exception.status_code == 422
    
    def test_not_found_exception(self):
        """测试资源未找到异常"""
        exception = NotFoundException(
            message="用户未找到",
            resource_type="用户",
            resource_id=123
        )
        
        assert exception.message == "用户 (ID: 123) 未找到"
        assert exception.error_code == "RESOURCE_NOT_FOUND"
        assert exception.status_code == 404
        assert exception.details["resource_type"] == "用户"
        assert exception.details["resource_id"] == "123"
    
    def test_conflict_exception(self):
        """测试冲突异常"""
        exception = ConflictException("资源冲突")
        
        assert exception.message == "资源冲突"
        assert exception.error_code == "RESOURCE_CONFLICT"
        assert exception.status_code == 409
    
    def test_database_exception(self):
        """测试数据库异常"""
        exception = DatabaseException(
            message="数据库错误",
            operation="INSERT",
            table="users"
        )
        
        assert "INSERT" in exception.message
        assert "users" in exception.message
        assert exception.error_code == "DATABASE_ERROR"
        assert exception.status_code == 500
        assert exception.details["operation"] == "INSERT"
        assert exception.details["table"] == "users"
    
    def test_external_service_exception(self):
        """测试外部服务异常"""
        exception = ExternalServiceException(
            message="外部服务错误",
            service_name="payment_service",
            endpoint="https://api.payment.com/charge"
        )
        
        assert "payment_service" in exception.message
        assert exception.error_code == "EXTERNAL_SERVICE_ERROR"
        assert exception.status_code == 502
        assert exception.details["service_name"] == "payment_service"
        assert exception.details["endpoint"] == "https://api.payment.com/charge"
    
    def test_rate_limit_exception(self):
        """测试限流异常"""
        exception = RateLimitException(
            message="限流",
            limit=100,
            window=3600
        )
        
        assert exception.message == "限流"
        assert exception.error_code == "RATE_LIMIT_EXCEEDED"
        assert exception.status_code == 429
        assert exception.details["limit"] == 100
        assert exception.details["window_seconds"] == 3600
    
    def test_user_already_exists_exception(self):
        """测试用户已存在异常"""
        exception = UserAlreadyExistsException(
            username="testuser",
            email="test@example.com"
        )
        
        assert "testuser" in exception.message
        assert "test@example.com" in exception.message
        assert exception.error_code == "USER_ALREADY_EXISTS"
        assert exception.status_code == 409
        assert exception.details["username"] == "testuser"
        assert exception.details["email"] == "test@example.com"
    
    def test_invalid_credentials_exception(self):
        """测试无效凭据异常"""
        exception = InvalidCredentialsException()
        
        assert exception.message == "用户名或密码错误"
        assert exception.error_code == "INVALID_CREDENTIALS"
        assert exception.status_code == 401
    
    def test_user_not_active_exception(self):
        """测试用户未激活异常"""
        exception = UserNotActiveException(user_id=123)
        
        assert "123" in exception.message
        assert exception.error_code == "USER_NOT_ACTIVE"
        assert exception.status_code == 401
        assert exception.details["user_id"] == "123"
    
    def test_permission_denied_exception(self):
        """测试权限拒绝异常"""
        exception = PermissionDeniedException(
            required_permissions=["user:create", "user:read"]
        )
        
        assert "user:create" in exception.message
        assert "user:read" in exception.message
        assert exception.error_code == "PERMISSION_DENIED"
        assert exception.status_code == 403
        assert exception.details["required_permissions"] == ["user:create", "user:read"]
    
    def test_resource_not_found_exception(self):
        """测试资源未找到异常"""
        exception = ResourceNotFoundException(
            resource_type="订单",
            resource_id="ORDER-123"
        )
        
        assert "订单" in exception.message
        assert "ORDER-123" in exception.message
        assert exception.error_code == "RESOURCE_NOT_FOUND"
        assert exception.status_code == 404
        assert exception.details["resource_type"] == "订单"
        assert exception.details["resource_id"] == "ORDER-123"


class TestGlobalExceptionHandlers:
    """全局异常处理器测试"""
    
    def setup_method(self):
        """设置测试环境"""
        self.app = FastAPI()
        setup_exception_handlers(self.app)
        self.client = TestClient(self.app)
    
    def test_business_exception_handler(self):
        """测试业务异常处理器"""
        @self.app.get("/test-business-exception")
        async def test_route():
            raise BusinessException("业务错误")
        
        response = self.client.get("/test-business-exception")
        assert response.status_code == 400
        
        data = response.json()
        assert data["success"] is False
        assert data["error_code"] == "BUSINESS_ERROR"
        assert data["message"] == "业务错误"
        assert data["status_code"] == 400
        assert "traceback_id" in data
    
    def test_authentication_exception_handler(self):
        """测试认证异常处理器"""
        @self.app.get("/test-authentication-exception")
        async def test_route():
            raise AuthenticationException("认证失败")
        
        response = self.client.get("/test-authentication-exception")
        assert response.status_code == 401
        
        data = response.json()
        assert data["success"] is False
        assert data["error_code"] == "AUTHENTICATION_FAILED"
        assert data["message"] == "认证失败"
        assert data["status_code"] == 401
        assert "traceback_id" in data
    
    def test_authorization_exception_handler(self):
        """测试授权异常处理器"""
        @self.app.get("/test-authorization-exception")
        async def test_route():
            raise AuthorizationException("权限不足")
        
        response = self.client.get("/test-authorization-exception")
        assert response.status_code == 403
        
        data = response.json()
        assert data["success"] is False
        assert data["error_code"] == "AUTHORIZATION_FAILED"
        assert data["message"] == "权限不足"
        assert data["status_code"] == 403
        assert "traceback_id" in data
    
    def test_validation_exception_handler(self):
        """测试验证异常处理器"""
        @self.app.get("/test-validation-exception")
        async def test_route():
            raise ValidationException("验证失败")
        
        response = self.client.get("/test-validation-exception")
        assert response.status_code == 422
        
        data = response.json()
        assert data["success"] is False
        assert data["error_code"] == "VALIDATION_FAILED"
        assert data["message"] == "验证失败"
        assert data["status_code"] == 422
        assert "traceback_id" in data
    
    def test_not_found_exception_handler(self):
        """测试资源未找到异常处理器"""
        @self.app.get("/test-not-found-exception")
        async def test_route():
            raise NotFoundException("资源未找到")
        
        response = self.client.get("/test-not-found-exception")
        assert response.status_code == 404
        
        data = response.json()
        assert data["success"] is False
        assert data["error_code"] == "RESOURCE_NOT_FOUND"
        assert data["message"] == "资源未找到"
        assert data["status_code"] == 404
        assert "traceback_id" in data
    
    def test_conflict_exception_handler(self):
        """测试冲突异常处理器"""
        @self.app.get("/test-conflict-exception")
        async def test_route():
            raise ConflictException("资源冲突")
        
        response = self.client.get("/test-conflict-exception")
        assert response.status_code == 409
        
        data = response.json()
        assert data["success"] is False
        assert data["error_code"] == "RESOURCE_CONFLICT"
        assert data["message"] == "资源冲突"
        assert data["status_code"] == 409
        assert "traceback_id" in data
    
    def test_general_exception_handler(self):
        """测试通用异常处理器"""
        @self.app.get("/test-general-exception")
        async def test_route():
            raise ValueError("通用错误")
        
        response = self.client.get("/test-general-exception")
        assert response.status_code == 500
        
        data = response.json()
        assert data["success"] is False
        assert data["error_code"] == "INTERNAL_SERVER_ERROR"
        assert data["message"] == "内部服务器错误"
        assert data["status_code"] == 500
        assert "traceback_id" in data


if __name__ == "__main__":
    pytest.main(["-v", "test_exceptions.py"])