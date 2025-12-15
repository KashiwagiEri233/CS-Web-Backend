"""
性能监控和慢查询检测模块
"""

import time
import asyncio
import threading

# psutil是可选依赖，用于系统资源监控
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None
from typing import Any, Callable, Dict, List, Optional, Union
from dataclasses import dataclass, field
from contextlib import contextmanager, asynccontextmanager
from functools import wraps
from collections import defaultdict, deque

from .context import PerformanceTracker, ContextManager, get_request_id, get_trace_id


@dataclass
class PerformanceThreshold:
    """性能阈值配置"""
    operation_name: str
    warning_threshold_ms: float = 1000.0  # 警告阈值（毫秒）
    error_threshold_ms: float = 3000.0   # 错误阈值（毫秒）
    sample_rate: float = 1.0             # 采样率（0.0-1.0）
    enabled: bool = True                  # 是否启用


@dataclass
class PerformanceAlert:
    """性能告警"""
    operation_name: str
    duration_ms: float
    threshold_type: str  # warning, error
    timestamp: float
    trace_id: Optional[str] = None
    request_id: Optional[str] = None
    extra_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'operation_name': self.operation_name,
            'duration_ms': self.duration_ms,
            'threshold_type': self.threshold_type,
            'timestamp': self.timestamp,
            'trace_id': self.trace_id,
            'request_id': self.request_id,
            'extra_data': self.extra_data
        }


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(
        self,
        enabled: bool = True,
        max_metrics_count: int = 1000,
        alert_handlers: Optional[List[Callable]] = None
    ):
        """初始化性能监控器"""
        self.enabled = enabled
        self.max_metrics_count = max_metrics_count
        self.alert_handlers = alert_handlers or []
        
        # 性能指标存储
        self._metrics = deque(maxlen=max_metrics_count)
        self._alerts = deque(maxlen=max_metrics_count)
        
        # 阈值配置
        self._thresholds: Dict[str, PerformanceThreshold] = {}
        
        # 统计信息
        self._stats = defaultdict(lambda: {
            'count': 0,
            'total_duration': 0.0,
            'min_duration': float('inf'),
            'max_duration': 0.0,
            'error_count': 0
        })
        
        # 线程锁
        self._lock = threading.RLock()
    
    def enable(self) -> None:
        """启用监控"""
        self.enabled = True
    
    def disable(self) -> None:
        """禁用监控"""
        self.enabled = False
    
    def set_threshold(
        self,
        operation_name: str,
        warning_threshold_ms: float = 1000.0,
        error_threshold_ms: float = 3000.0,
        sample_rate: float = 1.0,
        enabled: bool = True
    ) -> None:
        """设置性能阈值"""
        with self._lock:
            self._thresholds[operation_name] = PerformanceThreshold(
                operation_name=operation_name,
                warning_threshold_ms=warning_threshold_ms,
                error_threshold_ms=error_threshold_ms,
                sample_rate=sample_rate,
                enabled=enabled
            )
    
    def remove_threshold(self, operation_name: str) -> None:
        """移除阈值配置"""
        with self._lock:
            self._thresholds.pop(operation_name, None)
    
    def record_operation(
        self,
        operation_name: str,
        duration_ms: float,
        success: bool = True,
        **extra_data
    ) -> Optional[PerformanceAlert]:
        """记录操作性能"""
        if not self.enabled:
            return None
        
        timestamp = time.time()
        
        # 创建性能指标
        metric = {
            'operation_name': operation_name,
            'duration_ms': duration_ms,
            'success': success,
            'timestamp': timestamp,
            'trace_id': get_trace_id(),
            'request_id': get_request_id(),
            **extra_data
        }
        
        # 获取阈值配置
        threshold = self._thresholds.get(operation_name)
        
        # 采样检查
        if threshold and threshold.sample_rate < 1.0:
            import random
            if random.random() > threshold.sample_rate:
                return None
        
        with self._lock:
            # 存储指标
            self._metrics.append(metric)
            
            # 更新统计信息
            stats = self._stats[operation_name]
            stats['count'] += 1
            stats['total_duration'] += duration_ms
            stats['min_duration'] = min(stats['min_duration'], duration_ms)
            stats['max_duration'] = max(stats['max_duration'], duration_ms)
            
            if not success:
                stats['error_count'] += 1
            
            # 检查是否超过阈值
            alert = self._check_threshold(operation_name, duration_ms, timestamp, extra_data)
            if alert:
                self._alerts.append(alert)
                # 触发告警处理器
                self._trigger_alert_handlers(alert)
            
            return alert
    
    def _check_threshold(
        self,
        operation_name: str,
        duration_ms: float,
        timestamp: float,
        extra_data: Dict[str, Any]
    ) -> Optional[PerformanceAlert]:
        """检查是否超过阈值"""
        threshold = self._thresholds.get(operation_name)
        if not threshold or not threshold.enabled:
            return None
        
        alert_type = None
        if duration_ms >= threshold.error_threshold_ms:
            alert_type = 'error'
        elif duration_ms >= threshold.warning_threshold_ms:
            alert_type = 'warning'
        
        if alert_type:
            return PerformanceAlert(
                operation_name=operation_name,
                duration_ms=duration_ms,
                threshold_type=alert_type,
                timestamp=timestamp,
                trace_id=get_trace_id(),
                request_id=get_request_id(),
                extra_data=extra_data
            )
        
        return None
    
    def _trigger_alert_handlers(self, alert: PerformanceAlert) -> None:
        """触发告警处理器"""
        for handler in self.alert_handlers:
            try:
                handler(alert)
            except Exception as e:
                # 避免告警处理器本身出错
                print(f"Error in alert handler: {e}")
    
    def add_alert_handler(self, handler: Callable) -> None:
        """添加告警处理器"""
        if handler not in self.alert_handlers:
            self.alert_handlers.append(handler)
    
    def remove_alert_handler(self, handler: Callable) -> None:
        """移除告警处理器"""
        if handler in self.alert_handlers:
            self.alert_handlers.remove(handler)
    
    def get_metrics(
        self,
        operation_name: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """获取性能指标"""
        with self._lock:
            metrics = list(self._metrics)
        
        # 过滤条件
        if operation_name:
            metrics = [m for m in metrics if m['operation_name'] == operation_name]
        
        if start_time:
            metrics = [m for m in metrics if m['timestamp'] >= start_time]
        
        if end_time:
            metrics = [m for m in metrics if m['timestamp'] <= end_time]
        
        # 排序（按时间戳倒序）
        metrics.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # 限制数量
        if limit:
            metrics = metrics[:limit]
        
        return metrics
    
    def get_alerts(
        self,
        operation_name: Optional[str] = None,
        threshold_type: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """获取性能告警"""
        with self._lock:
            alerts = list(self._alerts)
        
        # 过滤条件
        if operation_name:
            alerts = [a for a in alerts if a.operation_name == operation_name]
        
        if threshold_type:
            alerts = [a for a in alerts if a.threshold_type == threshold_type]
        
        if start_time:
            alerts = [a for a in alerts if a.timestamp >= start_time]
        
        if end_time:
            alerts = [a for a in alerts if a.timestamp <= end_time]
        
        # 排序（按时间戳倒序）
        alerts.sort(key=lambda x: x.timestamp, reverse=True)
        
        # 限制数量
        if limit:
            alerts = alerts[:limit]
        
        return [alert.to_dict() for alert in alerts]
    
    def get_statistics(
        self,
        operation_name: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """获取统计信息"""
        with self._lock:
            stats = dict(self._stats)
        
        if operation_name:
            stats = {operation_name: stats.get(operation_name, {})}
        
        # 计算平均值
        for op_name, stat in stats.items():
            if stat['count'] > 0:
                stat['avg_duration'] = stat['total_duration'] / stat['count']
                stat['error_rate'] = stat['error_count'] / stat['count']
            
            # 重置最小值（如果没有数据）
            if stat['min_duration'] == float('inf'):
                stat['min_duration'] = 0
        
        return stats
    
    def clear_metrics(self) -> None:
        """清空所有指标"""
        with self._lock:
            self._metrics.clear()
            self._alerts.clear()
            self._stats.clear()


class SlowQueryMonitor:
    """慢查询监控器"""
    
    def __init__(
        self,
        slow_query_threshold_ms: float = 1000.0,
        enabled: bool = True,
        alert_handlers: Optional[List[Callable]] = None
    ):
        """初始化慢查询监控器"""
        self.slow_query_threshold_ms = slow_query_threshold_ms
        self.enabled = enabled
        self.alert_handlers = alert_handlers or []
        
        # 慢查询记录
        self._slow_queries = deque(maxlen=1000)
        
        # 线程锁
        self._lock = threading.RLock()
    
    def enable(self) -> None:
        """启用监控"""
        self.enabled = True
    
    def disable(self) -> None:
        """禁用监控"""
        self.enabled = False
    
    def record_query(
        self,
        query: str,
        duration_ms: float,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
        table: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None
    ) -> bool:
        """记录查询性能"""
        if not self.enabled:
            return False
        
        timestamp = time.time()
        
        # 检查是否为慢查询
        is_slow = duration_ms >= self.slow_query_threshold_ms
        
        if is_slow:
            slow_query = {
                'query': query,
                'parameters': parameters or {},
                'database': database,
                'table': table,
                'duration_ms': duration_ms,
                'timestamp': timestamp,
                'success': success,
                'error': error,
                'trace_id': get_trace_id(),
                'request_id': get_request_id()
            }
            
            with self._lock:
                self._slow_queries.append(slow_query)
            
            # 触发告警处理器
            self._trigger_alert_handlers(slow_query)
            
            return True
        
        return False
    
    def _trigger_alert_handlers(self, slow_query: Dict[str, Any]) -> None:
        """触发告警处理器"""
        for handler in self.alert_handlers:
            try:
                handler(slow_query)
            except Exception as e:
                # 避免告警处理器本身出错
                print(f"Error in slow query alert handler: {e}")
    
    def add_alert_handler(self, handler: Callable) -> None:
        """添加告警处理器"""
        if handler not in self.alert_handlers:
            self.alert_handlers.append(handler)
    
    def remove_alert_handler(self, handler: Callable) -> None:
        """移除告警处理器"""
        if handler in self.alert_handlers:
            self.alert_handlers.remove(handler)
    
    def get_slow_queries(
        self,
        database: Optional[str] = None,
        table: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """获取慢查询记录"""
        with self._lock:
            queries = list(self._slow_queries)
        
        # 过滤条件
        if database:
            queries = [q for q in queries if q.get('database') == database]
        
        if table:
            queries = [q for q in queries if q.get('table') == table]
        
        if start_time:
            queries = [q for q in queries if q['timestamp'] >= start_time]
        
        if end_time:
            queries = [q for q in queries if q['timestamp'] <= end_time]
        
        # 排序（按时间戳倒序）
        queries.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # 限制数量
        if limit:
            queries = queries[:limit]
        
        return queries
    
    def clear_slow_queries(self) -> None:
        """清空慢查询记录"""
        with self._lock:
            self._slow_queries.clear()


# 系统资源监控器
class SystemResourceMonitor:
    """系统资源监控器"""
    
    def __init__(self, enabled: bool = True, interval: float = 60.0):
        """初始化系统资源监控器"""
        self.enabled = enabled
        self.interval = interval
        self._monitoring = False
        self._monitor_thread = None
        self._resource_data = deque(maxlen=1000)
    
    def start_monitoring(self) -> None:
        """开始监控"""
        if self.enabled and not self._monitoring:
            self._monitoring = True
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True
            )
            self._monitor_thread.start()
    
    def stop_monitoring(self) -> None:
        """停止监控"""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join()
    
    def _monitor_loop(self) -> None:
        """监控循环"""
        while self._monitoring:
            try:
                # 收集系统资源信息
                resource_info = self._collect_resource_info()
                
                # 存储数据
                self._resource_data.append(resource_info)
                
                # 等待下一次采样
                time.sleep(self.interval)
                
            except Exception as e:
                print(f"Error in system resource monitoring: {e}")
                time.sleep(self.interval)
    
    def _collect_resource_info(self) -> Dict[str, Any]:
        """收集系统资源信息"""
        timestamp = time.time()
        
        if not PSUTIL_AVAILABLE:
            return {
                'timestamp': timestamp,
                'error': 'psutil not available - install with pip install psutil'
            }
        
        try:
            # CPU信息
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            
            # 内存信息
            memory = psutil.virtual_memory()
            
            # 磁盘信息 - 使用当前目录
            disk = psutil.disk_usage('.')
            
            # 网络信息
            network = psutil.net_io_counters()
            
            return {
                'timestamp': timestamp,
                'cpu': {
                    'percent': cpu_percent,
                    'count': cpu_count
                },
                'memory': {
                    'total': memory.total,
                    'available': memory.available,
                    'percent': memory.percent,
                    'used': memory.used,
                    'free': memory.free
                },
                'disk': {
                    'total': disk.total,
                    'used': disk.used,
                    'free': disk.free,
                    'percent': (disk.used / disk.total) * 100
                },
                'network': {
                    'bytes_sent': network.bytes_sent,
                    'bytes_recv': network.bytes_recv,
                    'packets_sent': network.packets_sent,
                    'packets_recv': network.packets_recv
                }
            }
        except Exception as e:
            return {
                'timestamp': timestamp,
                'error': str(e)
            }
    
    def get_resource_data(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """获取资源监控数据"""
        data = list(self._resource_data)
        
        # 过滤条件
        if start_time:
            data = [d for d in data if d['timestamp'] >= start_time]
        
        if end_time:
            data = [d for d in data if d['timestamp'] <= end_time]
        
        # 排序（按时间戳倒序）
        data.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # 限制数量
        if limit:
            data = data[:limit]
        
        return data


# 全局实例
performance_monitor = PerformanceMonitor()
slow_query_monitor = SlowQueryMonitor()
resource_monitor = SystemResourceMonitor()


# 上下文管理器
@contextmanager
def monitor_performance(operation_name: str, **extra_data):
    """性能监控上下文管理器"""
    start_time = time.time()
    success = True
    
    try:
        yield
    except Exception as e:
        success = False
        extra_data['error'] = str(e)
        extra_data['error_type'] = type(e).__name__
        raise
    finally:
        duration_ms = (time.time() - start_time) * 1000
        performance_monitor.record_operation(
            operation_name,
            duration_ms,
            success,
            **extra_data
        )


@asynccontextmanager
async def monitor_performance_async(operation_name: str, **extra_data):
    """异步性能监控上下文管理器"""
    start_time = time.time()
    success = True
    
    try:
        yield
    except Exception as e:
        success = False
        extra_data['error'] = str(e)
        extra_data['error_type'] = type(e).__name__
        raise
    finally:
        duration_ms = (time.time() - start_time) * 1000
        performance_monitor.record_operation(
            operation_name,
            duration_ms,
            success,
            **extra_data
        )


@contextmanager
def monitor_database_query(query: str, database: str = None, table: str = None, **parameters):
    """数据库查询监控上下文管理器"""
    start_time = time.time()
    success = True
    error = None
    
    try:
        yield
    except Exception as e:
        success = False
        error = str(e)
        raise
    finally:
        duration_ms = (time.time() - start_time) * 1000
        slow_query_monitor.record_query(
            query,
            duration_ms,
            parameters=parameters,
            database=database,
            table=table,
            success=success,
            error=error
        )


# 装饰器
def performance_tracked(operation_name: str = None):
    """性能追踪装饰器"""
    def decorator(func: Callable) -> Callable:
        name = operation_name or f"{func.__module__}.{func.__name__}"
        
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                async with monitor_performance_async(name, args=args, kwargs=kwargs):
                    return await func(*args, **kwargs)
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                with monitor_performance(name, args=args, kwargs=kwargs):
                    return func(*args, **kwargs)
            return sync_wrapper
    
    return decorator


def slow_query_tracked(query: str = None, database: str = None, table: str = None):
    """慢查询追踪装饰器"""
    def decorator(func: Callable) -> Callable:
        query_str = query or func.__name__
        
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                with monitor_database_query(query_str, database, table, **kwargs):
                    return await func(*args, **kwargs)
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                with monitor_database_query(query_str, database, table, **kwargs):
                    return func(*args, **kwargs)
            return sync_wrapper
    
    return decorator


# 便捷函数
def setup_performance_monitoring(
    enabled: bool = True,
    slow_query_threshold_ms: float = 1000.0,
    monitor_resources: bool = True,
    resource_interval: float = 60.0
) -> None:
    """设置性能监控"""
    # 启用/禁用性能监控
    performance_monitor.enabled = enabled
    slow_query_monitor.enabled = enabled
    
    # 设置慢查询阈值
    slow_query_monitor.slow_query_threshold_ms = slow_query_threshold_ms
    
    # 启动系统资源监控
    if monitor_resources:
        resource_monitor.enabled = enabled
        resource_monitor.interval = resource_interval
        resource_monitor.start_monitoring()


def get_performance_summary() -> Dict[str, Any]:
    """获取性能摘要"""
    return {
        'performance_stats': performance_monitor.get_statistics(),
        'slow_queries_count': len(slow_query_monitor._slow_queries),
        'system_resources': resource_monitor.get_resource_data(limit=1)
    }