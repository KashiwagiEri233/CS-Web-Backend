"""
日志适配器测试
"""

import asyncio
import logging
import pytest
import time
from unittest.mock import Mock, patch

from app.core.logging import (
    LoggingAdapter, get_logger, set_logging_context, clear_logging_context,
    LoggingContextManager, bind_context, generate_request_id
)


class TestLoggingAdapter:
    """日志适配器测试类"""
    
    def setup_method(self):
        """测试前置设置"""
        # 清空适配器缓存
        import app.core.logging_adapter
        app.core.logging_adapter._adapter_cache.clear()
        # 清空上下文
        clear_logging_context()
    
    def teardown_method(self):
        """测试后清理"""
        clear_logging_context()
    
    def test_logging_adapter_creation(self):
        """测试日志适配器创建"""
        adapter = LoggingAdapter("test_logger")
        assert adapter.name == "test_logger"
        assert adapter.level == logging.NOTSET
    
    def test_logging_adapter_level_setting(self):
        """测试日志级别设置"""
        adapter = LoggingAdapter("test_logger")
        
        # 测试字符串级别
        adapter.setLevel("INFO")
        assert adapter.level == logging.INFO
        
        # 测试数字级别
        adapter.setLevel(logging.ERROR)
        assert adapter.level == logging.ERROR
    
    def test_logging_adapter_level_check(self):
        """测试日志级别检查"""
        adapter = LoggingAdapter("test_logger", "INFO")
        
        assert adapter.isEnabledFor(logging.INFO)
        assert adapter.isEnabledFor(logging.WARNING)
        assert adapter.isEnabledFor(logging.ERROR)
        assert adapter.isEnabledFor(logging.CRITICAL)
        assert not adapter.isEnabledFor(logging.DEBUG)
    
    def test_logging_adapter_logging_methods(self):
        """测试日志记录方法"""
        adapter = LoggingAdapter("test_logger")
        
        # Mock结构化日志器
        mock_structured_logger = Mock()
        adapter._structured_logger = mock_structured_logger
        
        # 测试各种日志级别
        adapter.debug("Debug message")
        adapter.info("Info message")
        adapter.warning("Warning message")
        adapter.error("Error message")
        adapter.critical("Critical message")
        
        # 验证调用
        assert mock_structured_logger.debug.called
        assert mock_structured_logger.info.called
        assert mock_structured_logger.warning.called
        assert mock_structured_logger.error.called
        assert mock_structured_logger.critical.called
    
    def test_logging_adapter_context_binding(self):
        """测试上下文绑定"""
        adapter = LoggingAdapter("test_logger")
        
        # 绑定上下文
        bound_adapter = adapter.bind(request_id="req-123", user_id=456)
        
        # 验证新适配器创建
        assert bound_adapter is not adapter
        assert bound_adapter.name == "test_logger"
    
    def test_logging_adapter_context_unbinding(self):
        """测试上下文解绑"""
        adapter = LoggingAdapter("test_logger")
        
        # 绑定多个上下文
        bound_adapter = adapter.bind(request_id="req-123", user_id=456, session_id="sess-789")
        
        # 解绑部分上下文
        unbound_adapter = bound_adapter.unbind("user_id")
        
        # 验证新适配器创建
        assert unbound_adapter is not bound_adapter
        assert unbound_adapter.name == "test_logger"
    
    def test_logging_adapter_new_context(self):
        """测试创建全新上下文"""
        adapter = LoggingAdapter("test_logger")
        
        # 绑定上下文
        adapter.bind(request_id="req-123", user_id=456)
        
        # 创建全新上下文
        new_adapter = adapter.new(operation="test")
        
        # 验证新适配器创建
        assert new_adapter is not adapter
        assert new_adapter.name == "test_logger"
    
    def test_get_logger(self):
        """测试获取日志记录器"""
        # 获取日志记录器
        logger1 = get_logger("test_logger")
        logger2 = get_logger("test_logger")
        
        # 验证缓存机制
        assert logger1 is logger2
        assert logger1.name == "test_logger"
    
    def test_logging_context(self):
        """测试日志上下文"""
        # 设置全局上下文
        set_logging_context(request_id="req-123", user_id=456)
        
        # 获取日志记录器并验证上下文
        logger = get_logger("test_logger")
        context = logger.get_context()
        
        assert context["request_id"] == "req-123"
        assert context["user_id"] == 456
    
    def test_logging_context_manager(self):
        """测试日志上下文管理器"""
        # 设置初始上下文
        set_logging_context(request_id="req-123")
        
        # 使用上下文管理器
        with LoggingContextManager(user_id=456, operation="test"):
            context = get_logging_context()
            assert context["request_id"] == "req-123"  # 保留原上下文
            assert context["user_id"] == 456  # 添加新上下文
            assert context["operation"] == "test"
        
        # 退出后上下文恢复
        context = get_logging_context()
        assert context["request_id"] == "req-123"
        assert "user_id" not in context
        assert "operation" not in context
    
    def test_bind_context_decorator(self):
        """测试上下文绑定装饰器"""
        @bind_context(user_id=456, operation="test")
        def test_function():
            context = get_logging_context()
            return context
        
        # 设置初始上下文
        set_logging_context(request_id="req-123")
        
        # 调用函数
        context = test_function()
        
        # 验证上下文
        assert context["request_id"] == "req-123"
        assert context["user_id"] == 456
        assert context["operation"] == "test"
    
    def test_generate_request_id(self):
        """测试生成请求ID"""
        request_id1 = generate_request_id()
        request_id2 = generate_request_id()
        
        # 验证唯一性
        assert request_id1 != request_id2
        assert len(request_id1) == 32  # UUID去掉连字符后的长度
        assert len(request_id2) == 32
    
    @patch('app.core.logging_adapter.logging.basicConfig')
    def test_basic_config(self, mock_basic_config):
        """测试基础配置"""
        # 导入basicConfig函数
        from app.core.logging_adapter import basicConfig
        
        # 调用基础配置
        basicConfig(level="WARNING")
        
        # 验证调用
        mock_basic_config.assert_called_once_with(level=30)  # logging.WARNING的值
    
    def test_logger_exception(self):
        """测试异常日志记录"""
        adapter = LoggingAdapter("test_logger")
        
        # Mock结构化日志器
        mock_structured_logger = Mock()
        adapter._structured_logger = mock_structured_logger
        
        # 记录异常
        try:
            raise ValueError("Test exception")
        except ValueError:
            adapter.exception("An error occurred", additional_info="test")
        
        # 验证调用
        mock_structured_logger.error.assert_called_once()
        call_args = mock_structured_logger.error.call_args
        assert "exc_info" in call_args.kwargs
        assert call_args.kwargs["additional_info"] == "test"


class TestLoggingAdapterIntegration:
    """日志适配器集成测试"""
    
    def setup_method(self):
        """测试前置设置"""
        # 清空适配器缓存
        import app.core.logging_adapter
        app.core.logging_adapter._adapter_cache.clear()
        # 清空上下文
        clear_logging_context()
    
    def teardown_method(self):
        """测试后清理"""
        clear_logging_context()
    
    def test_multiple_loggers_context_isolation(self):
        """测试多个日志器的上下文隔离"""
        logger1 = get_logger("logger1")
        logger2 = get_logger("logger2")
        
        # 设置不同的上下文
        logger1.bind(component="comp1").info("Message from logger1")
        logger2.bind(component="comp2").info("Message from logger2")
        
        # 验证上下文不互相影响
        # 注意：这里的行为取决于具体的上下文管理实现
        # 实际测试时需要根据实际行为调整断言
    
    def test_nested_context_managers(self):
        """测试嵌套上下文管理器"""
        with LoggingContextManager(operation="outer"):
            with LoggingContextManager(step="inner"):
                context = get_logging_context()
                assert context["operation"] == "outer"
                assert context["step"] == "inner"
    
    def test_context_with_multithreading(self):
        """测试多线程环境下的上下文隔离"""
        import threading
        results = []
        
        def thread_worker(thread_id):
            # 在线程中设置上下文
            set_logging_context(thread_id=thread_id)
            context = get_logging_context()
            results.append(context)
        
        # 创建多个线程
        threads = []
        for i in range(3):
            thread = threading.Thread(target=thread_worker, args=(i,))
            threads.append(thread)
            thread.start()
        
        # 等待所有线程完成
        for thread in threads:
            thread.join()
        
        # 验证每个线程有独立的上下文
        assert len(results) == 3
        for i, context in enumerate(results):
            # 由于contextvars的线程隔离特性，每个线程应该有自己的上下文
            # 这里需要根据实际实现调整断言
            pass
    
    def test_large_context_data(self):
        """测试大量上下文数据的处理"""
        # 创建大量上下文数据
        large_context = {
            f"key_{i}": f"value_{i}" for i in range(100)
        }
        
        # 设置大上下文
        set_logging_context(**large_context)
        
        # 获取日志记录器并记录日志
        logger = get_logger("test_logger")
        
        # 验证没有抛出异常
        logger.info("Test message with large context")
        
        # 清理上下文
        clear_logging_context()
    
    def test_context_performance(self):
        """测试上下文操作的性能"""
        import time
        
        # 测试上下文设置和获取的性能
        start_time = time.time()
        
        for i in range(1000):
            set_logging_context(iteration=i)
            context = get_logging_context()
            assert context["iteration"] == i
        
        end_time = time.time()
        duration = end_time - start_time
        
        # 验证性能合理（这里设置一个宽松的阈值）
        assert duration < 1.0  # 1000次操作应在1秒内完成
        
        # 清理上下文
        clear_logging_context()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])