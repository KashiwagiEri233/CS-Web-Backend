"""
日志系统集成测试
"""

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from app.core.logging import (
    # 系统配置
    AdvancedLoggingSystem, configure_logging, start_logging_system, stop_logging_system,
    
    # 核心组件
    get_logger, set_logging_context, clear_logging_context,
    LoggingContextManager,
    
    # 上下文追踪
    TraceManager, RequestTracker, PerformanceTracker,
    LoggingContextMiddleware,
    get_request_id, get_trace_id, get_user_id,
    
    # 性能监控
    performance_monitor, slow_query_monitor,
    monitor_performance, performance_tracked,
    
    # 数据库集成
    DatabaseConfig, LogEntry, MCPDatabaseLogger,
    
    # FastAPI集成
    integrate_with_fastapi,
    
    # 处理器
    create_colored_console_handler, setup_log_files,
)


class TestLoggingSystemIntegration:
    """日志系统集成测试"""
    
    def setup_method(self):
        """测试前置设置"""
        # 创建临时目录用于日志文件
        self.temp_dir = tempfile.mkdtemp()
        self.log_dir = os.path.join(self.temp_dir, "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 清空上下文
        clear_logging_context()
        
        # 重置全局监控器
        performance_monitor.clear_metrics()
        slow_query_monitor.clear_slow_queries()
    
    def teardown_method(self):
        """测试后清理"""
        # 清理临时文件
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        
        # 清空上下文
        clear_logging_context()
        
        # 重置全局监控器
        performance_monitor.clear_metrics()
        slow_query_monitor.clear_slow_queries()
    
    def test_basic_logging_integration(self):
        """测试基础日志集成"""
        # 配置日志系统
        configure_logging(
            level="INFO",
            enable_console=True,
            enable_file=True,
            log_dir=self.log_dir,
            app_name="test_app"
        )
        
        # 获取日志记录器
        logger = get_logger("integration_test")
        
        # 记录不同级别的日志
        logger.debug("Debug message")
        logger.info("Info message", key="value")
        logger.warning("Warning message", warning_code=401)
        logger.error("Error message", error="Test error")
        
        # 验证日志文件创建
        log_files = list(Path(self.log_dir).glob("*.log"))
        assert len(log_files) > 0
    
    def test_context_integration(self):
        """测试上下文集成"""
        # 配置日志系统
        configure_logging(
            level="INFO",
            enable_console=True
        )
        
        # 设置全局上下文
        set_logging_context(request_id="req-123", user_id=456)
        
        # 获取日志记录器
        logger = get_logger("context_test")
        
        # 记录日志
        logger.info("Message with context", operation="test")
        
        # 使用上下文管理器
        with LoggingContextManager(step="validation", module="auth"):
            logger.info("Validation message")
            
            with LoggingContextManager(substep="password_check"):
                logger.info("Password check message")
        
        # 验证上下文隔离
        context = get_logging_context()
        assert "request_id" not in context or context.get("request_id") != "req-123"
        assert "step" not in context
        assert "substep" not in context
    
    def test_performance_integration(self):
        """测试性能监控集成"""
        # 配置日志系统
        configure_logging(
            level="INFO",
            enable_console=True,
            enable_performance=True,
            performance_thresholds={
                "test_operation": {"warning": 100.0, "error": 200.0}
            }
        )
        
        # 获取日志记录器
        logger = get_logger("performance_test")
        
        # 使用性能监控装饰器
        @performance_tracked("test_operation")
        def test_function():
            time.sleep(0.15)  # 150ms，应该触发警告
            return "result"
        
        # 调用函数
        result = test_function()
        assert result == "result"
        
        # 使用性能监控上下文管理器
        with monitor_performance("context_operation", type="test"):
            time.sleep(0.12)  # 120ms
            logger.info("Operation completed")
        
        # 验证性能指标记录
        metrics = performance_monitor.get_metrics()
        assert len(metrics) == 2
        
        # 验证告警
        alerts = performance_monitor.get_alerts()
        assert len(alerts) >= 1
    
    def test_file_handler_integration(self):
        """测试文件处理器集成"""
        # 配置日志系统
        configure_logging(
            level="INFO",
            enable_file=True,
            log_dir=self.log_dir,
            app_name="file_test",
            file_max_size_mb=1,
            file_backup_count=3
        )
        
        # 获取日志记录器
        logger = get_logger("file_test")
        
        # 记录大量日志以触发轮转
        for i in range(1000):
            logger.info(f"Log message {i}", iteration=i)
        
        # 验证日志文件创建
        log_files = list(Path(self.log_dir).glob("*.log*"))
        assert len(log_files) >= 1
        
        # 验证日志内容
        app_log = Path(self.log_dir) / "file_test.log"
        if app_log.exists():
            content = app_log.read_text()
            assert "Log message 0" in content
            assert "Log message 999" in content
    
    def test_advanced_logging_system_class(self):
        """测试高级日志系统类"""
        # 创建日志系统实例
        logging_system = AdvancedLoggingSystem()
        
        # 配置系统
        logging_system.configure(
            level="INFO",
            enable_console=True,
            enable_file=True,
            log_dir=self.log_dir,
            app_name="advanced_test"
        )
        
        # 获取日志记录器
        logger = logging_system.get_logger("class_test")
        
        # 设置上下文
        logging_system.set_context(request_id="req-456")
        
        # 使用上下文管理器
        with logging_system.with_context(operation="test"):
            logger.info("Test message")
        
        # 使用装饰器
        @logging_system.trace_operation("traced_function")
        def traced_function():
            logger.info("Traced function")
            return "result"
        
        # 调用函数
        result = traced_function()
        assert result == "result"
        
        # 获取性能摘要
        summary = logging_system.get_performance_summary()
        assert "performance_stats" in summary
    
    @pytest.mark.asyncio
    async def test_async_integration(self):
        """测试异步集成"""
        # 配置日志系统
        configure_logging(
            level="INFO",
            enable_console=True
        )
        
        # 获取日志记录器
        logger = get_logger("async_test")
        
        # 异步日志记录
        async def async_function():
            logger.info("Async function started")
            await asyncio.sleep(0.1)
            logger.info("Async function completed")
            return "async_result"
        
        # 调用异步函数
        result = await async_function()
        assert result == "async_result"
        
        # 异步性能监控
        from app.core.logging import monitor_performance_async
        
        async with monitor_performance_async("async_operation", type="test"):
            await asyncio.sleep(0.1)
            logger.info("Async operation completed")
        
        # 验证性能指标
        metrics = performance_monitor.get_metrics()
        assert any(m["operation_name"] == "async_operation" for m in metrics)
    
    def test_fastapi_integration(self):
        """测试FastAPI集成"""
        # 这里只测试配置部分，不实际运行FastAPI应用
        from fastapi import FastAPI
        
        # 创建应用
        app = FastAPI(title="Test App")
        
        # 集成日志系统
        app = integrate_with_fastapi(
            app,
            level="INFO",
            enable_console=True,
            enable_file=True,
            log_dir=self.log_dir
        )
        
        # 验证中间件已添加
        middleware_types = [type(middleware.cls) for middleware in app.user_middleware]
        
        # 检查是否有LoggingContextMiddleware
        from app.core.logging import LoggingContextMiddleware
        assert LoggingContextMiddleware in middleware_types
    
    def test_error_handling_integration(self):
        """测试错误处理集成"""
        # 配置日志系统
        configure_logging(
            level="INFO",
            enable_console=True
        )
        
        # 获取日志记录器
        logger = get_logger("error_test")
        
        # 记录异常
        try:
            raise ValueError("Test exception")
        except ValueError:
            logger.exception("An exception occurred", context="test")
        
        # 记录错误
        logger.error("An error occurred", error_code=500, error_details="Test error")
    
    def test_high_volume_logging(self):
        """测试高并发日志记录"""
        # 配置日志系统
        configure_logging(
            level="INFO",
            enable_console=True,
            enable_file=True,
            log_dir=self.log_dir,
            app_name="volume_test"
        )
        
        # 获取日志记录器
        logger = get_logger("volume_test")
        
        # 多线程日志记录
        import threading
        
        def log_worker(worker_id):
            for i in range(100):
                logger.info(f"Worker {worker_id} message {i}", worker_id=worker_id, iteration=i)
        
        # 创建多个线程
        threads = []
        for worker_id in range(5):
            thread = threading.Thread(target=log_worker, args=(worker_id,))
            threads.append(thread)
            thread.start()
        
        # 等待所有线程完成
        for thread in threads:
            thread.join()
        
        # 验证所有日志都被记录
        log_files = list(Path(self.log_dir).glob("*.log"))
        assert len(log_files) >= 1
    
    def test_context_var_isolation(self):
        """测试上下文变量隔离"""
        # 配置日志系统
        configure_logging(
            level="INFO",
            enable_console=True
        )
        
        # 测试上下文隔离
        def context_test():
            # 设置上下文
            set_logging_context(operation="test", value="original")
            
            # 嵌套上下文
            with LoggingContextManager(nested=True):
                set_logging_context(operation="nested", value="changed")
                
                # 验证嵌套上下文
                context = get_logging_context()
                # 这里需要根据实际实现调整断言
                pass
            
            # 验证上下文恢复
            context = get_logging_context()
            # 这里需要根据实际实现调整断言
        
        # 运行测试
        context_test()
    
    def test_custom_processor_integration(self):
        """测试自定义处理器集成"""
        # 这里只测试处理器创建，不测试完整集成
        from app.core.logging.handlers import create_colored_console_handler
        
        # 创建自定义处理器
        handler = create_colored_console_handler(
            level="DEBUG",
            use_colors=True,
            show_details=True
        )
        
        # 验证处理器属性
        assert handler.level == logging.DEBUG
    
    def test_memory_usage(self):
        """测试内存使用"""
        # 配置日志系统
        configure_logging(
            level="INFO",
            enable_console=True
        )
        
        # 获取日志记录器
        logger = get_logger("memory_test")
        
        # 记录大量日志
        for i in range(10000):
            logger.info(f"Message {i}", iteration=i, data="x" * 100)  # 较大的数据
        
        # 验证没有内存泄漏
        # 这里可以添加内存使用检查，但需要根据实际需求实现
    
    @pytest.mark.asyncio
    async def test_database_integration_mock(self):
        """测试数据库集成（模拟）"""
        # 模拟数据库配置
        db_config = DatabaseConfig(
            host="localhost",
            port=5432,
            database="test_logs",
            username="postgres",
            password="password"
        )
        
        # 创建日志条目
        entry = LogEntry(
            timestamp=time.time(),
            level="INFO",
            logger_name="test_logger",
            message="Test message",
            trace_id="trace-123",
            request_id="req-123",
            user_id=456
        )
        
        # 验证日志条目转换
        entry_dict = entry.to_dict()
        assert entry_dict["level"] == "INFO"
        assert entry_dict["logger_name"] == "test_logger"
        assert entry_dict["message"] == "Test message"
        assert entry_dict["trace_id"] == "trace-123"
        assert entry_dict["request_id"] == "req-123"
        assert entry_dict["user_id"] == 456


class TestEndToEndScenarios:
    """端到端场景测试"""
    
    def setup_method(self):
        """测试前置设置"""
        # 创建临时目录用于日志文件
        self.temp_dir = tempfile.mkdtemp()
        self.log_dir = os.path.join(self.temp_dir, "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 清空上下文
        clear_logging_context()
        
        # 重置全局监控器
        performance_monitor.clear_metrics()
        slow_query_monitor.clear_slow_queries()
    
    def teardown_method(self):
        """测试后清理"""
        # 清理临时文件
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        
        # 清空上下文
        clear_logging_context()
        
        # 重置全局监控器
        performance_monitor.clear_metrics()
        slow_query_monitor.clear_slow_queries()
    
    def test_web_api_scenario(self):
        """测试Web API场景"""
        # 配置日志系统
        configure_logging(
            level="INFO",
            enable_console=True,
            enable_file=True,
            enable_performance=True,
            log_dir=self.log_dir,
            app_name="web_api",
            performance_thresholds={
                "api_request": {"warning": 500.0, "error": 1000.0},
                "database_query": {"warning": 100.0, "error": 200.0}
            }
        )
        
        # 模拟API请求处理
        @performance_tracked("api_request")
        def handle_api_request(user_id, endpoint):
            # 设置请求上下文
            set_logging_context(
                request_id="req-123",
                user_id=user_id,
                endpoint=endpoint
            )
            
            logger = get_logger("api_handler")
            
            # 记录请求开始
            logger.info(f"Processing {endpoint} request", user_id=user_id)
            
            # 模拟数据库查询
            with monitor_performance("database_query", table="users", query_type="SELECT"):
                time.sleep(0.15)  # 模拟慢查询
                logger.info("Database query completed", result_count=10)
            
            # 处理业务逻辑
            with LoggingContextManager(step="business_logic"):
                logger.info("Processing business logic")
                # 模拟处理时间
                time.sleep(0.2)
            
            # 记录请求完成
            logger.info(f"{endpoint} request completed", user_id=user_id)
            
            return {"status": "success", "data": []}
        
        # 调用API处理函数
        result = handle_api_request(456, "/api/users")
        assert result["status"] == "success"
        
        # 验证日志文件创建
        log_files = list(Path(self.log_dir).glob("*.log"))
        assert len(log_files) >= 1
        
        # 验证性能指标
        metrics = performance_monitor.get_metrics()
        assert len(metrics) >= 2  # 至少有API请求和数据库查询
        
        # 验证告警
        alerts = performance_monitor.get_alerts()
        # 应该有一些性能告警，因为模拟的操作比较慢
        assert len(alerts) >= 1
    
    def test_user_journey_scenario(self):
        """测试用户旅程场景"""
        # 配置日志系统
        configure_logging(
            level="INFO",
            enable_console=True,
            enable_file=True,
            log_dir=self.log_dir,
            app_name="user_journey"
        )
        
        # 模拟用户旅程
        def simulate_user_journey():
            logger = get_logger("user_journey")
            
            # 用户登录
            with LoggingContextManager(step="login", user_id=789):
                logger.info("User login attempt", email="user@example.com")
                
                # 验证凭据
                with LoggingContextManager(substep="credential_check"):
                    time.sleep(0.1)
                    logger.info("Credentials verified", success=True)
                
                # 创建会话
                with LoggingContextManager(substep="session_creation"):
                    session_id = "sess-123"
                    logger.info("Session created", session_id=session_id)
                
                logger.info("User login successful", user_id=789)
            
            # 用户浏览产品
            with LoggingContextManager(step="browse_products", user_id=789):
                logger.info("Browsing products", category="electronics")
                
                # 搜索产品
                with monitor_performance("product_search", query="laptop", category="electronics"):
                    time.sleep(0.2)
                    logger.info("Search completed", result_count=25)
                
                # 查看产品详情
                with LoggingContextManager(substep="view_product", product_id=1001):
                    logger.info("Viewing product details", product_id=1001)
            
            # 用户购买产品
            with LoggingContextManager(step="purchase", user_id=789):
                logger.info("Starting purchase process", product_id=1001)
                
                # 处理支付
                with LoggingContextManager(substep="payment", payment_method="credit_card"):
                    logger.info("Processing payment", amount=999.99)
                    
                    # 支付处理（模拟）
                    with monitor_performance("payment_processing", payment_method="credit_card"):
                        time.sleep(0.3)
                        logger.info("Payment processed", transaction_id="txn-456")
                
                # 创建订单
                with LoggingContextManager(substep="order_creation"):
                    order_id = "order-789"
                    logger.info("Order created", order_id=order_id)
                
                logger.info("Purchase completed", order_id=order_id, amount=999.99)
        
        # 运行用户旅程模拟
        simulate_user_journey()
        
        # 验证日志文件创建
        log_files = list(Path(self.log_dir).glob("*.log"))
        assert len(log_files) >= 1
        
        # 验证性能指标
        metrics = performance_monitor.get_metrics()
        assert len(metrics) >= 2  # 至少有搜索和支付处理
    
    def test_error_handling_scenario(self):
        """测试错误处理场景"""
        # 配置日志系统
        configure_logging(
            level="INFO",
            enable_console=True,
            enable_file=True,
            log_dir=self.log_dir,
            app_name="error_handling"
        )
        
        logger = get_logger("error_scenario")
        
        # 模拟各种错误场景
        try:
            # 业务逻辑错误
            raise ValueError("Invalid input parameter")
        except ValueError as e:
            logger.exception("Business logic error", error_type="ValueError", input_param="invalid")
        
        # 记录系统错误
        logger.error(
            "System error occurred",
            error_code=500,
            error_message="Database connection failed",
            service="auth_service"
        )
        
        # 记录安全事件
        logger.warning(
            "Security event detected",
            event_type="brute_force_attempt",
            source_ip="192.168.1.100",
            target_user="admin"
        )
        
        # 模拟部分失败操作
        with LoggingContextManager(operation="partial_failure", success_rate=0.7):
            logger.info("Processing batch", total_items=100, failed_items=30)
            
            for i in range(30):
                logger.warning(
                    "Item processing failed",
                    item_id=i + 1,
                    error="Invalid format"
                )
        
        # 验证日志文件创建
        log_files = list(Path(self.log_dir).glob("*.log"))
        assert len(log_files) >= 1
    
    def test_performance_monitoring_scenario(self):
        """测试性能监控场景"""
        # 配置日志系统
        configure_logging(
            level="INFO",
            enable_console=True,
            enable_file=True,
            enable_performance=True,
            log_dir=self.log_dir,
            app_name="performance_test"
        )
        
        # 设置性能阈值
        performance_monitor.set_threshold(
            "slow_operation",
            warning_threshold_ms=200.0,
            error_threshold_ms=500.0
        )
        
        # 模拟各种性能场景
        @performance_tracked("normal_operation")
        def normal_operation():
            time.sleep(0.1)
            return "normal_result"
        
        @performance_tracked("slow_operation")
        def slow_operation():
            time.sleep(0.3)  # 触发警告
            return "slow_result"
        
        @performance_tracked("very_slow_operation")
        def very_slow_operation():
            time.sleep(0.6)  # 触发错误
            return "very_slow_result"
        
        # 执行操作
        normal_operation()
        slow_operation()
        very_slow_operation()
        
        # 模拟数据库慢查询
        with monitor_performance("database_query", table="large_table", query_type="SELECT"):
            time.sleep(0.25)
        
        # 验证性能指标
        metrics = performance_monitor.get_metrics()
        assert len(metrics) >= 4
        
        # 验证告警
        alerts = performance_monitor.get_alerts()
        assert len(alerts) >= 2  # 至少有slow_operation的警告和very_slow_operation的错误
        
        # 验证统计信息
        stats = performance_monitor.get_statistics()
        assert "normal_operation" in stats
        assert "slow_operation" in stats
        assert "very_slow_operation" in stats
        
        # 验证统计数据的正确性
        normal_stats = stats["normal_operation"]
        assert normal_stats["count"] == 1
        assert normal_stats["error_count"] == 0
        
        slow_stats = stats["slow_operation"]
        assert slow_stats["count"] == 1
        assert slow_stats["error_count"] == 0
        
        very_slow_stats = stats["very_slow_operation"]
        assert very_slow_stats["count"] == 1
        assert very_slow_stats["error_count"] == 0  # 慢操作不一定是错误


if __name__ == "__main__":
    pytest.main([__file__, "-v"])