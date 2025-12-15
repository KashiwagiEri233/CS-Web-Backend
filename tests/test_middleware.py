import pytest
from unittest.mock import MagicMock, patch
from fastapi import Request, Response
from starlette.datastructures import Headers

from app.middleware.monitoring import LoggingMiddleware, SecurityHeadersMiddleware, MetricsMiddleware


class TestLoggingMiddleware:
    """日志中间件测试"""
    
    @pytest.mark.asyncio
    async def test_logging_middleware_success(self):
        """测试成功请求的日志记录"""
        # 创建模拟的请求和响应
        request = MagicMock(spec=Request)
        request.method = "GET"
        request.url = MagicMock()
        request.url.path = "/test"
        request.url.query = ""
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = Headers({})
        
        response = MagicMock(spec=Response)
        response.status_code = 200
        
        # 模拟 call_next 函数
        async def call_next(req):
            return response
        
        middleware = LoggingMiddleware(app=None)
        with patch('app.core.logging.log_user_action') as mock_log:
            await middleware.dispatch(request, call_next)
            
            # 验证日志记录被调用
            mock_log.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_logging_middleware_with_exception(self):
        """测试异常请求的日志记录"""
        request = MagicMock(spec=Request)
        request.method = "POST"
        request.url = MagicMock()
        request.url.path = "/api/test"
        request.url.query = ""
        request.client = MagicMock()
        request.client.host = "192.168.1.1"
        request.headers = Headers({"user-agent": "TestAgent"})
        
        # 模拟异常
        async def call_next(req):
            raise ValueError("Test exception")
        
        middleware = LoggingMiddleware(app=None)
        # 修改测试以验证log_exception被调用而不是log_user_action
        with patch('app.core.logging.log_exception') as mock_log_exception:
            try:
                await middleware.dispatch(request, call_next)
            except ValueError:
                pass
            
            # 验证错误日志记录被调用
            mock_log_exception.assert_called_once()


class TestSecurityHeadersMiddleware:
    """安全头中间件测试"""
    
    @pytest.mark.asyncio
    async def test_security_headers_middleware(self):
        """测试安全头的添加"""
        request = MagicMock(spec=Request)
        
        response = MagicMock(spec=Response)
        response.headers = {}
        
        async def call_next(req):
            return response
        
        middleware = SecurityHeadersMiddleware(app=None)
        result = await middleware.dispatch(request, call_next)
        
        # 验证安全头已添加
        assert "X-Content-Type-Options" in result.headers
        assert "X-Frame-Options" in result.headers
        assert "X-XSS-Protection" in result.headers
        assert "Strict-Transport-Security" in result.headers


class TestMetricsMiddleware:
    """指标中间件测试"""
    
    @pytest.mark.asyncio
    async def test_metrics_collection(self):
        """测试指标收集"""
        request = MagicMock(spec=Request)
        request.method = "GET"
        request.url = MagicMock()
        request.url.path = "/api/v1/test"
        
        response = MagicMock(spec=Response)
        response.status_code = 200
        
        async def call_next(req):
            return response
        
        middleware = MetricsMiddleware(app=None)
        await middleware.dispatch(request, call_next)
        
        # 验证指标记录已更新
        metrics = middleware.get_metrics()
        assert metrics["requests"]["total"] == 1
        assert metrics["requests"]["by_status"]["200"] == 1
        assert metrics["requests"]["by_method"]["GET"] == 1
        assert "/api/v1/test" in metrics["requests"]["by_path"]
    
    @pytest.mark.asyncio
    async def test_metrics_getter(self):
        """测试指标获取方法"""
        middleware = MetricsMiddleware(app=None)
        metrics = middleware.get_metrics()
        
        # 验证指标结构
        assert "requests" in metrics
        assert "performance" in metrics
        assert "security" in metrics
        assert "uptime_seconds" in metrics
        
        # 验证初始值
        assert metrics["requests"]["total"] == 0
        assert metrics["security"]["auth_failures"] == 0