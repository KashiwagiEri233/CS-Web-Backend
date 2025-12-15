"""
性能监控测试
"""

import asyncio
import time
import pytest
from unittest.mock import Mock, patch

from app.core.logging.performance import (
    PerformanceMonitor, SlowQueryMonitor, SystemResourceMonitor,
    PerformanceThreshold, PerformanceAlert,
    performance_monitor, slow_query_monitor, resource_monitor,
    monitor_performance, monitor_performance_async,
    performance_traced, slow_query_tracked,
    setup_performance_monitoring, get_performance_summary
)


class TestPerformanceThreshold:
    """性能阈值测试类"""
    
    def test_performance_threshold_creation(self):
        """测试性能阈值创建"""
        threshold = PerformanceThreshold(
            operation_name="test_operation",
            warning_threshold_ms=500.0,
            error_threshold_ms=1000.0,
            sample_rate=0.5,
            enabled=True
        )
        
        assert threshold.operation_name == "test_operation"
        assert threshold.warning_threshold_ms == 500.0
        assert threshold.error_threshold_ms == 1000.0
        assert threshold.sample_rate == 0.5
        assert threshold.enabled is True
    
    def test_performance_alert_creation(self):
        """测试性能告警创建"""
        alert = PerformanceAlert(
            operation_name="test_operation",
            duration_ms=750.0,
            threshold_type="warning",
            timestamp=time.time(),
            trace_id="trace-123",
            request_id="req-123",
            extra_data={"key": "value"}
        )
        
        assert alert.operation_name == "test_operation"
        assert alert.duration_ms == 750.0
        assert alert.threshold_type == "warning"
        assert alert.trace_id == "trace-123"
        assert alert.request_id == "req-123"
        assert alert.extra_data == {"key": "value"}
    
    def test_performance_alert_to_dict(self):
        """测试性能告警转换为字典"""
        alert = PerformanceAlert(
            operation_name="test_operation",
            duration_ms=750.0,
            threshold_type="warning",
            timestamp=time.time(),
            trace_id="trace-123",
            request_id="req-123"
        )
        
        alert_dict = alert.to_dict()
        
        assert isinstance(alert_dict, dict)
        assert alert_dict["operation_name"] == "test_operation"
        assert alert_dict["duration_ms"] == 750.0
        assert alert_dict["threshold_type"] == "warning"
        assert alert_dict["trace_id"] == "trace-123"
        assert alert_dict["request_id"] == "req-123"


class TestPerformanceMonitor:
    """性能监控器测试类"""
    
    def setup_method(self):
        """测试前置设置"""
        self.monitor = PerformanceMonitor(
            enabled=True,
            max_metrics_count=100,
            alert_handlers=[]
        )
    
    def test_performance_monitor_enable_disable(self):
        """测试性能监控器启用/禁用"""
        assert self.monitor.enabled is True
        
        self.monitor.disable()
        assert self.monitor.enabled is False
        
        self.monitor.enable()
        assert self.monitor.enabled is True
    
    def test_set_threshold(self):
        """测试设置性能阈值"""
        self.monitor.set_threshold(
            "test_operation",
            warning_threshold_ms=500.0,
            error_threshold_ms=1000.0,
            sample_rate=0.8,
            enabled=False
        )
        
        threshold = self.monitor._thresholds["test_operation"]
        assert threshold.operation_name == "test_operation"
        assert threshold.warning_threshold_ms == 500.0
        assert threshold.error_threshold_ms == 1000.0
        assert threshold.sample_rate == 0.8
        assert threshold.enabled is False
    
    def test_remove_threshold(self):
        """测试移除性能阈值"""
        # 设置阈值
        self.monitor.set_threshold("test_operation")
        
        # 验证阈值存在
        assert "test_operation" in self.monitor._thresholds
        
        # 移除阈值
        self.monitor.remove_threshold("test_operation")
        
        # 验证阈值不存在
        assert "test_operation" not in self.monitor._thresholds
    
    def test_record_operation(self):
        """测试记录操作性能"""
        # 设置阈值
        self.monitor.set_threshold(
            "test_operation",
            warning_threshold_ms=500.0,
            error_threshold_ms=1000.0
        )
        
        # 记录正常操作
        alert = self.monitor.record_operation(
            "test_operation",
            duration_ms=300.0,
            success=True,
            param1="value1"
        )
        
        # 应该没有告警
        assert alert is None
        
        # 记录慢操作
        alert = self.monitor.record_operation(
            "test_operation",
            duration_ms=750.0,
            success=True,
            param1="value1"
        )
        
        # 应该有警告告警
        assert alert is not None
        assert alert.threshold_type == "warning"
        assert alert.duration_ms == 750.0
        
        # 记录超慢操作
        alert = self.monitor.record_operation(
            "test_operation",
            duration_ms=1500.0,
            success=True,
            param1="value1"
        )
        
        # 应该有错误告警
        assert alert is not None
        assert alert.threshold_type == "error"
        assert alert.duration_ms == 1500.0
    
    def test_record_operation_with_sampling(self):
        """测试带采样的操作记录"""
        # 设置低采样率阈值
        self.monitor.set_threshold(
            "test_operation",
            warning_threshold_ms=500.0,
            sample_rate=0.1  # 10%采样率
        )
        
        # 记录多次操作
        recorded_count = 0
        for i in range(100):
            alert = self.monitor.record_operation(
                "test_operation",
                duration_ms=100.0,  # 快速操作，不会触发告警
                success=True
            )
            if alert is not None or len(self.monitor._metrics) > 0:
                recorded_count += 1
        
        # 由于采样率低，记录次数应该远小于总次数
        assert recorded_count < 20  # 允许一定随机性
    
    def test_add_remove_alert_handler(self):
        """测试添加和移除告警处理器"""
        # 创建模拟处理器
        handler1 = Mock()
        handler2 = Mock()
        
        # 添加处理器
        self.monitor.add_alert_handler(handler1)
        assert handler1 in self.monitor.alert_handlers
        
        self.monitor.add_alert_handler(handler2)
        assert handler2 in self.monitor.alert_handlers
        
        # 移除处理器
        self.monitor.remove_alert_handler(handler1)
        assert handler1 not in self.monitor.alert_handlers
        assert handler2 in self.monitor.alert_handlers
    
    def test_trigger_alert_handlers(self):
        """测试触发告警处理器"""
        # 创建模拟处理器
        handler = Mock()
        self.monitor.add_alert_handler(handler)
        
        # 设置阈值
        self.monitor.set_threshold(
            "test_operation",
            warning_threshold_ms=500.0
        )
        
        # 记录慢操作，应该触发告警
        self.monitor.record_operation(
            "test_operation",
            duration_ms=750.0,
            success=True
        )
        
        # 验证处理器被调用
        handler.assert_called_once()
        
        # 验证传递的告警对象
        alert = handler.call_args[0][0]
        assert isinstance(alert, PerformanceAlert)
        assert alert.operation_name == "test_operation"
        assert alert.duration_ms == 750.0
    
    def test_get_metrics(self):
        """测试获取性能指标"""
        # 记录多个指标
        self.monitor.record_operation("op1", 100.0, True)
        self.monitor.record_operation("op2", 200.0, True)
        self.monitor.record_operation("op1", 150.0, False)
        
        # 获取所有指标
        metrics = self.monitor.get_metrics()
        assert len(metrics) == 3
        
        # 按操作名过滤
        op1_metrics = self.monitor.get_metrics(operation_name="op1")
        assert len(op1_metrics) == 2
        
        # 按时间过滤
        now = time.time()
        recent_metrics = self.monitor.get_metrics(start_time=now - 1)
        assert len(recent_metrics) == 3
        
        # 限制数量
        limited_metrics = self.monitor.get_metrics(limit=2)
        assert len(limited_metrics) == 2
    
    def test_get_alerts(self):
        """测试获取告警"""
        # 设置阈值
        self.monitor.set_threshold("test_operation", warning_threshold_ms=500.0)
        
        # 生成告警
        self.monitor.record_operation("test_operation", 750.0, True)
        self.monitor.record_operation("test_operation", 1500.0, True)
        
        # 获取所有告警
        alerts = self.monitor.get_alerts()
        assert len(alerts) == 2
        
        # 按类型过滤
        warning_alerts = self.monitor.get_alerts(threshold_type="warning")
        error_alerts = self.monitor.get_alerts(threshold_type="error")
        
        assert len(warning_alerts) == 1
        assert len(error_alerts) == 1
        
        # 限制数量
        limited_alerts = self.monitor.get_alerts(limit=1)
        assert len(limited_alerts) == 1
    
    def test_get_statistics(self):
        """测试获取统计信息"""
        # 记录多个指标
        self.monitor.record_operation("op1", 100.0, True)
        self.monitor.record_operation("op1", 200.0, True)
        self.monitor.record_operation("op1", 150.0, False)
        self.monitor.record_operation("op2", 300.0, True)
        
        # 获取所有统计信息
        stats = self.monitor.get_statistics()
        
        assert "op1" in stats
        assert "op2" in stats
        
        op1_stats = stats["op1"]
        assert op1_stats["count"] == 3
        assert op1_stats["total_duration"] == 450.0
        assert op1_stats["min_duration"] == 100.0
        assert op1_stats["max_duration"] == 200.0
        assert op1_stats["error_count"] == 1
        assert op1_stats["avg_duration"] == 150.0
        assert op1_stats["error_rate"] == 1.0 / 3.0
        
        # 获取特定操作的统计信息
        op1_only_stats = self.monitor.get_statistics(operation_name="op1")
        assert "op1" in op1_only_stats
        assert "op2" not in op1_only_stats
    
    def test_clear_metrics(self):
        """测试清空指标"""
        # 记录指标
        self.monitor.record_operation("test_operation", 100.0, True)
        
        # 验证有指标
        assert len(self.monitor._metrics) > 0
        assert len(self.monitor._alerts) >= 0
        assert len(self.monitor._stats) > 0
        
        # 清空指标
        self.monitor.clear_metrics()
        
        # 验证指标已清空
        assert len(self.monitor._metrics) == 0
        assert len(self.monitor._alerts) == 0
        assert len(self.monitor._stats) == 0


class TestSlowQueryMonitor:
    """慢查询监控器测试类"""
    
    def setup_method(self):
        """测试前置设置"""
        self.monitor = SlowQueryMonitor(
            slow_query_threshold_ms=1000.0,
            enabled=True,
            alert_handlers=[]
        )
    
    def test_slow_query_monitor_enable_disable(self):
        """测试慢查询监控器启用/禁用"""
        assert self.monitor.enabled is True
        
        self.monitor.disable()
        assert self.monitor.enabled is False
        
        self.monitor.enable()
        assert self.monitor.enabled is True
    
    def test_record_query(self):
        """测试记录查询"""
        # 记录快速查询
        is_slow = self.monitor.record_query(
            query="SELECT * FROM users",
            duration_ms=500.0,
            database="app_db",
            table="users"
        )
        
        # 不应该记录为慢查询
        assert is_slow is False
        assert len(self.monitor._slow_queries) == 0
        
        # 记录慢查询
        is_slow = self.monitor.record_query(
            query="SELECT * FROM large_table",
            duration_ms=1500.0,
            parameters={"limit": 1000},
            database="app_db",
            table="large_table",
            success=True
        )
        
        # 应该记录为慢查询
        assert is_slow is True
        assert len(self.monitor._slow_queries) == 1
        
        # 验证慢查询记录
        slow_query = self.monitor._slow_queries[0]
        assert slow_query["query"] == "SELECT * FROM large_table"
        assert slow_query["duration_ms"] == 1500.0
        assert slow_query["database"] == "app_db"
        assert slow_query["table"] == "large_table"
        assert slow_query["parameters"] == {"limit": 1000}
        assert slow_query["success"] is True
        assert "timestamp" in slow_query
    
    def test_record_failed_query(self):
        """测试记录失败查询"""
        # 记录失败的慢查询
        is_slow = self.monitor.record_query(
            query="SELECT * FROM invalid_table",
            duration_ms=1200.0,
            database="app_db",
            table="invalid_table",
            success=False,
            error="Table 'invalid_table' doesn't exist"
        )
        
        # 应该记录为慢查询
        assert is_slow is True
        assert len(self.monitor._slow_queries) == 1
        
        # 验证慢查询记录
        slow_query = self.monitor._slow_queries[0]
        assert slow_query["success"] is False
        assert slow_query["error"] == "Table 'invalid_table' doesn't exist"
    
    def test_get_slow_queries(self):
        """测试获取慢查询"""
        # 记录多个慢查询
        self.monitor.record_query(
            "SELECT * FROM users", 1200.0, database="db1", table="users"
        )
        self.monitor.record_query(
            "SELECT * FROM products", 1500.0, database="db2", table="products"
        )
        self.monitor.record_query(
            "SELECT * FROM orders", 1800.0, database="db1", table="orders"
        )
        
        # 获取所有慢查询
        all_queries = self.monitor.get_slow_queries()
        assert len(all_queries) == 3
        
        # 按数据库过滤
        db1_queries = self.monitor.get_slow_queries(database="db1")
        assert len(db1_queries) == 2
        
        db2_queries = self.monitor.get_slow_queries(database="db2")
        assert len(db2_queries) == 1
        
        # 按表过滤
        users_queries = self.monitor.get_slow_queries(table="users")
        assert len(users_queries) == 1
        
        # 限制数量
        limited_queries = self.monitor.get_slow_queries(limit=2)
        assert len(limited_queries) == 2
    
    def test_clear_slow_queries(self):
        """测试清空慢查询"""
        # 记录慢查询
        self.monitor.record_query("SELECT * FROM users", 1200.0)
        
        # 验证有记录
        assert len(self.monitor._slow_queries) > 0
        
        # 清空记录
        self.monitor.clear_slow_queries()
        
        # 验证记录已清空
        assert len(self.monitor._slow_queries) == 0
    
    def test_add_remove_alert_handler(self):
        """测试添加和移除告警处理器"""
        # 创建模拟处理器
        handler = Mock()
        
        # 添加处理器
        self.monitor.add_alert_handler(handler)
        assert handler in self.monitor.alert_handlers
        
        # 记录慢查询，应该触发告警
        self.monitor.record_query("SELECT * FROM users", 1200.0)
        
        # 验证处理器被调用
        handler.assert_called_once()
        
        # 移除处理器
        self.monitor.remove_alert_handler(handler)
        assert handler not in self.monitor.alert_handlers


class TestPerformanceDecorators:
    """性能装饰器测试类"""
    
    def test_performance_tracked_decorator(self):
        """测试性能追踪装饰器"""
        # 重置全局监控器
        performance_monitor.clear_metrics()
        
        # 设置阈值
        performance_monitor.set_threshold(
            "test_function",
            warning_threshold_ms=100.0,
            error_threshold_ms=200.0
        )
        
        # 应用装饰器
        @performance_tracked("test_function")
        def test_function():
            time.sleep(0.15)  # 150ms，应该触发警告
            return "result"
        
        # 调用函数
        result = test_function()
        
        # 验证结果
        assert result == "result"
        
        # 验证性能记录
        metrics = performance_monitor.get_metrics()
        assert len(metrics) == 1
        assert metrics[0]["operation_name"] == "test_function"
        assert metrics[0]["duration_ms"] >= 150.0
        assert metrics[0]["success"] is True
        
        # 验证告警
        alerts = performance_monitor.get_alerts()
        assert len(alerts) == 1
        assert alerts[0]["operation_name"] == "test_function"
        assert alerts[0]["threshold_type"] == "warning"
    
    def test_slow_query_tracked_decorator(self):
        """测试慢查询追踪装饰器"""
        # 重置慢查询监控器
        slow_query_monitor.clear_slow_queries()
        
        # 应用装饰器
        @slow_query_tracked("SELECT * FROM large_table", database="app_db", table="large_table")
        def test_query():
            time.sleep(0.12)  # 120ms，超过100ms阈值
            return [{"id": 1, "name": "test"}]
        
        # 调用函数
        result = test_query()
        
        # 验证结果
        assert result == [{"id": 1, "name": "test"}]
        
        # 验证慢查询记录
        slow_queries = slow_query_monitor.get_slow_queries()
        assert len(slow_queries) == 1
        assert slow_queries[0]["query"] == "SELECT * FROM large_table"
        assert slow_queries[0]["database"] == "app_db"
        assert slow_queries[0]["table"] == "large_table"
        assert slow_queries[0]["duration_ms"] >= 120.0
        assert slow_queries[0]["success"] is True
    
    @pytest.mark.asyncio
    async def test_async_performance_monitoring(self):
        """测试异步性能监控"""
        # 重置全局监控器
        performance_monitor.clear_metrics()
        
        # 使用异步上下文管理器
        async with monitor_performance_async("async_operation", type="test"):
            await asyncio.sleep(0.1)  # 100ms
            await asyncio.sleep(0.05)  # 再50ms，总共150ms
        
        # 验证性能记录
        metrics = performance_monitor.get_metrics()
        assert len(metrics) == 1
        assert metrics[0]["operation_name"] == "async_operation"
        assert metrics[0]["duration_ms"] >= 150.0
        assert metrics[0]["success"] is True
        assert metrics[0]["type"] == "test"
    
    def test_performance_context_manager(self):
        """测试性能上下文管理器"""
        # 重置全局监控器
        performance_monitor.clear_metrics()
        
        # 使用上下文管理器
        with monitor_performance("context_operation", param1="value1"):
            time.sleep(0.1)  # 100ms
            # 模拟工作
        
        # 验证性能记录
        metrics = performance_monitor.get_metrics()
        assert len(metrics) == 1
        assert metrics[0]["operation_name"] == "context_operation"
        assert metrics[0]["duration_ms"] >= 100.0
        assert metrics[0]["success"] is True
        assert metrics[0]["param1"] == "value1"
    
    def test_database_query_context_manager(self):
        """测试数据库查询上下文管理器"""
        # 重置慢查询监控器
        slow_query_monitor.clear_slow_queries()
        
        # 使用上下文管理器
        with monitor_database_query(
            "SELECT * FROM products WHERE price > 100",
            database="shop_db",
            table="products",
            min_price=100
        ):
            time.sleep(0.12)  # 120ms，超过100ms阈值
            # 模拟查询
        
        # 验证慢查询记录
        slow_queries = slow_query_monitor.get_slow_queries()
        assert len(slow_queries) == 1
        assert slow_queries[0]["query"] == "SELECT * FROM products WHERE price > 100"
        assert slow_queries[0]["database"] == "shop_db"
        assert slow_queries[0]["table"] == "products"
        assert slow_queries[0]["duration_ms"] >= 120.0
        assert slow_queries[0]["success"] is True
        assert slow_queries[0]["parameters"]["min_price"] == 100


class TestSystemResourceMonitor:
    """系统资源监控器测试类"""
    
    def test_resource_monitor_creation(self):
        """测试资源监控器创建"""
        monitor = SystemResourceMonitor(enabled=True, interval=60.0)
        
        assert monitor.enabled is True
        assert monitor.interval == 60.0
        assert monitor._monitoring is False
        assert monitor._monitor_thread is None
    
    def test_resource_monitor_start_stop(self):
        """测试资源监控器启动和停止"""
        monitor = SystemResourceMonitor(enabled=True, interval=0.1)  # 短间隔用于测试
        
        # 启动监控
        monitor.start_monitoring()
        assert monitor._monitoring is True
        assert monitor._monitor_thread is not None
        
        # 等待一段时间收集数据
        time.sleep(0.2)
        
        # 停止监控
        monitor.stop_monitoring()
        assert monitor._monitoring is False
        
        # 验证有数据收集
        resource_data = monitor.get_resource_data()
        assert len(resource_data) > 0
    
    def test_get_resource_data(self):
        """测试获取资源数据"""
        monitor = SystemResourceMonitor(enabled=True, interval=0.1)
        
        # 手动添加测试数据
        monitor._resource_data.append({
            'timestamp': time.time(),
            'cpu': {'percent': 50.0, 'count': 4},
            'memory': {'total': 8000000000, 'available': 4000000000, 'percent': 50.0},
        })
        
        # 获取数据
        data = monitor.get_resource_data()
        assert len(data) == 1
        assert 'cpu' in data[0]
        assert 'memory' in data[0]
        assert 'timestamp' in data[0]
        
        # 测试过滤
        cpu_data = monitor.get_resource_data(limit=1)
        assert len(cpu_data) == 1


class TestPerformanceSetup:
    """性能设置测试类"""
    
    def test_setup_performance_monitoring(self):
        """测试设置性能监控"""
        # 重置全局监控器
        performance_monitor.clear_metrics()
        slow_query_monitor.clear_slow_queries()
        
        # 设置性能监控
        setup_performance_monitoring(
            enabled=True,
            slow_query_threshold_ms=500.0,
            monitor_resources=True,
            resource_interval=60.0
        )
        
        # 验证设置
        assert performance_monitor.enabled is True
        assert slow_query_monitor.enabled is True
        assert slow_query_monitor.slow_query_threshold_ms == 500.0
        assert resource_monitor.enabled is True
        assert resource_monitor.interval == 60.0
    
    def test_get_performance_summary(self):
        """测试获取性能摘要"""
        # 重置全局监控器
        performance_monitor.clear_metrics()
        slow_query_monitor.clear_slow_queries()
        
        # 添加一些测试数据
        performance_monitor.record_operation("test_op", 100.0, True)
        slow_query_monitor.record_query("SELECT * FROM test", 600.0)
        
        # 获取摘要
        summary = get_performance_summary()
        
        # 验证摘要结构
        assert 'performance_stats' in summary
        assert 'slow_queries_count' in summary
        assert 'system_resources' in summary
        
        # 验证数据
        assert summary['slow_queries_count'] == 1
        assert 'test_op' in summary['performance_stats']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])