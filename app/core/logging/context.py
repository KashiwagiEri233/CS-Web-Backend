"""
请求上下文追踪模块
实现分布式追踪和请求生命周期管理
"""

import uuid
import time
import threading
from contextvars import ContextVar, copy_context
from typing import Any, Dict, Optional, List, Callable
from dataclasses import dataclass, field
from fastapi import Request, Response
try:
    from fastapi.concurrency import contextvars_in_copy_context
except ImportError:
    # 如果导入失败，定义一个简单的替代实现
    def contextvars_in_copy_context(func):
        """上下文变量复制装饰器的简单替代实现"""
        def wrapper(*args, **kwargs):
            return copy_context().run(func, *args, **kwargs)
        return wrapper

# 上下文变量
_request_context: ContextVar[Dict[str, Any]] = ContextVar('request_context', default={})
_trace_context: ContextVar[Dict[str, Any]] = ContextVar('trace_context', default={})
_performance_context: ContextVar[Dict[str, Any]] = ContextVar('performance_context', default={})


@dataclass
class TraceInfo:
    """分布式追踪信息"""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    operation_name: str = ""
    start_time: float = field(default_factory=time.time)
    tags: Dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # ok, error, timeout
    service_name: str = "fastapi_app"
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'trace_id': self.trace_id,
            'span_id': self.span_id,
            'parent_span_id': self.parent_span_id,
            'operation_name': self.operation_name,
            'start_time': self.start_time,
            'duration': time.time() - self.start_time,
            'tags': self.tags,
            'status': self.status,
            'service_name': self.service_name
        }


@dataclass
class RequestInfo:
    """请求信息"""
    request_id: str
    method: str
    url: str
    query_params: Dict[str, Any] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    client_ip: str = ""
    user_agent: str = ""
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'request_id': self.request_id,
            'method': self.method,
            'url': self.url,
            'query_params': self.query_params,
            'client_ip': self.client_ip,
            'user_agent': self.user_agent,
            'user_id': self.user_id,
            'session_id': self.session_id,
            'start_time': self.start_time,
            'duration': time.time() - self.start_time
        }


@dataclass
class PerformanceMetrics:
    """性能指标"""
    operation_name: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration: Optional[float] = None
    memory_usage: Optional[Dict[str, int]] = None
    cpu_usage: Optional[float] = None
    custom_metrics: Dict[str, Any] = field(default_factory=dict)
    
    def finish(self) -> None:
        """完成计时"""
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'operation_name': self.operation_name,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration': self.duration,
            'memory_usage': self.memory_usage,
            'cpu_usage': self.cpu_usage,
            'custom_metrics': self.custom_metrics
        }


class ContextManager:
    """上下文管理器"""
    
    @staticmethod
    def get_request_context() -> Dict[str, Any]:
        """获取请求上下文"""
        return _request_context.get()
    
    @staticmethod
    def set_request_context(context: Dict[str, Any]) -> None:
        """设置请求上下文"""
        _request_context.set(context)
    
    @staticmethod
    def update_request_context(**kwargs) -> None:
        """更新请求上下文"""
        current = _request_context.get().copy()
        current.update(kwargs)
        _request_context.set(current)
    
    @staticmethod
    def get_trace_context() -> Dict[str, Any]:
        """获取追踪上下文"""
        return _trace_context.get()
    
    @staticmethod
    def set_trace_context(context: Dict[str, Any]) -> None:
        """设置追踪上下文"""
        _trace_context.set(context)
    
    @staticmethod
    def update_trace_context(**kwargs) -> None:
        """更新追踪上下文"""
        current = _trace_context.get().copy()
        current.update(kwargs)
        _trace_context.set(current)
    
    @staticmethod
    def get_performance_context() -> Dict[str, Any]:
        """获取性能上下文"""
        return _performance_context.get()
    
    @staticmethod
    def set_performance_context(context: Dict[str, Any]) -> None:
        """设置性能上下文"""
        _performance_context.set(context)
    
    @staticmethod
    def update_performance_context(**kwargs) -> None:
        """更新性能上下文"""
        current = _performance_context.get().copy()
        current.update(kwargs)
        _performance_context.set(current)
    
    @staticmethod
    def clear_all_contexts() -> None:
        """清空所有上下文"""
        _request_context.set({})
        _trace_context.set({})
        _performance_context.set({})


class TraceManager:
    """追踪管理器"""
    
    @staticmethod
    def generate_trace_id() -> str:
        """生成追踪ID"""
        return str(uuid.uuid4()).replace('-', '')
    
    @staticmethod
    def generate_span_id() -> str:
        """生成Span ID"""
        return str(uuid.uuid4())[:16]
    
    @staticmethod
    def start_trace(
        operation_name: str,
        parent_span_id: Optional[str] = None,
        **tags
    ) -> TraceInfo:
        """开始一个新的追踪"""
        trace_id = TraceManager.generate_trace_id()
        span_id = TraceManager.generate_span_id()
        
        trace = TraceInfo(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            operation_name=operation_name,
            tags=tags
        )
        
        # 设置到追踪上下文
        ContextManager.set_trace_context(trace.to_dict())
        
        return trace
    
    @staticmethod
    def finish_trace(status: str = "ok", **extra_tags) -> TraceInfo:
        """完成当前追踪"""
        trace_data = ContextManager.get_trace_context()
        if not trace_data:
            return None
        
        # 更新状态和额外标签
        trace_data['status'] = status
        trace_data['duration'] = time.time() - trace_data['start_time']
        trace_data['tags'].update(extra_tags)
        
        # 更新上下文
        ContextManager.set_trace_context(trace_data)
        
        return TraceInfo(**trace_data)
    
    @staticmethod
    def create_span(
        operation_name: str,
        parent_span_id: Optional[str] = None,
        **tags
    ) -> TraceInfo:
        """创建子Span"""
        trace_data = ContextManager.get_trace_context()
        
        # 如果有现有追踪，使用其trace_id
        if trace_data:
            trace_id = trace_data['trace_id']
            if not parent_span_id:
                parent_span_id = trace_data['span_id']
        else:
            trace_id = TraceManager.generate_trace_id()
        
        span_id = TraceManager.generate_span_id()
        
        span = TraceInfo(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            operation_name=operation_name,
            tags=tags
        )
        
        return span
    
    @staticmethod
    def get_current_trace() -> Optional[Dict[str, Any]]:
        """获取当前追踪信息"""
        return ContextManager.get_trace_context()


class RequestTracker:
    """请求追踪器"""
    
    @staticmethod
    def start_tracking(request: Request) -> RequestInfo:
        """开始追踪请求"""
        request_id = str(uuid.uuid4()).replace('-', '')
        
        # 提取客户端信息
        client_ip = request.client.host if request.client else ""
        user_agent = request.headers.get("user-agent", "")
        
        # 提取查询参数
        query_params = dict(request.query_params) if request.query_params else {}
        
        request_info = RequestInfo(
            request_id=request_id,
            method=request.method,
            url=str(request.url),
            query_params=query_params,
            headers=dict(request.headers),
            client_ip=client_ip,
            user_agent=user_agent
        )
        
        # 设置到请求上下文
        ContextManager.set_request_context(request_info.to_dict())
        
        # 同时设置到追踪上下文
        if not ContextManager.get_trace_context():
            TraceManager.start_trace(f"HTTP {request.method}", operation_name=str(request.url))
        
        # 将请求ID添加到追踪上下文
        ContextManager.update_trace_context(request_id=request_id)
        
        return request_info
    
    @staticmethod
    def finish_tracking(response: Response, status_code: Optional[int] = None) -> RequestInfo:
        """完成请求追踪"""
        request_data = ContextManager.get_request_context()
        if not request_data:
            return None
        
        # 更新响应信息
        if status_code:
            request_data['status_code'] = status_code
        elif hasattr(response, 'status_code'):
            request_data['status_code'] = response.status_code
        
        # 计算处理时间
        request_data['duration'] = time.time() - request_data['start_time']
        
        # 更新上下文
        ContextManager.set_request_context(request_data)
        
        return RequestInfo(**request_data)
    
    @staticmethod
    def add_user_info(user_id: int, session_id: Optional[str] = None) -> None:
        """添加用户信息到请求上下文"""
        user_info = {'user_id': user_id}
        if session_id:
            user_info['session_id'] = session_id
        
        ContextManager.update_request_context(**user_info)
    
    @staticmethod
    def get_current_request() -> Optional[Dict[str, Any]]:
        """获取当前请求信息"""
        return ContextManager.get_request_context()


class PerformanceTracker:
    """性能追踪器"""
    
    @staticmethod
    def start_operation(operation_name: str, **custom_metrics) -> str:
        """开始性能追踪"""
        operation_id = str(uuid.uuid4())[:8]
        
        metrics = PerformanceMetrics(
            operation_name=operation_name,
            custom_metrics=custom_metrics
        )
        
        # 获取当前性能上下文
        perf_context = ContextManager.get_performance_context()
        perf_context[operation_id] = metrics
        
        ContextManager.set_performance_context(perf_context)
        
        return operation_id
    
    @staticmethod
    def finish_operation(operation_id: str, **additional_metrics) -> PerformanceMetrics:
        """完成性能追踪"""
        perf_context = ContextManager.get_performance_context()
        
        if operation_id not in perf_context:
            return None
        
        metrics = perf_context[operation_id]
        metrics.finish()
        
        # 添加额外的指标
        if additional_metrics:
            metrics.custom_metrics.update(additional_metrics)
        
        # 更新上下文
        perf_context[operation_id] = metrics
        ContextManager.set_performance_context(perf_context)
        
        return metrics
    
    @staticmethod
    def get_operation_metrics(operation_id: str) -> Optional[PerformanceMetrics]:
        """获取操作性能指标"""
        perf_context = ContextManager.get_performance_context()
        return perf_context.get(operation_id)
    
    @staticmethod
    def get_all_metrics() -> Dict[str, PerformanceMetrics]:
        """获取所有性能指标"""
        return ContextManager.get_performance_context()
    
    @staticmethod
    def clear_metrics() -> None:
        """清空性能指标"""
        ContextManager.set_performance_context({})


class LoggingContextMiddleware:
    """FastAPI日志上下文中间件"""
    
    def __init__(self, app, include_trace: bool = True, include_performance: bool = True):
        """初始化中间件"""
        self.app = app
        self.include_trace = include_trace
        self.include_performance = include_performance
    
    async def __call__(self, scope, receive, send):
        """中间件处理"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        # 创建Request对象
        request = Request(scope, receive)
        
        # 开始请求追踪
        request_tracker = RequestTracker.start_tracking(request)
        
        # 开始性能追踪（如果启用）
        operation_id = None
        if self.include_performance:
            operation_id = PerformanceTracker.start_operation(
                f"{request.method} {request.url.path}",
                method=request.method,
                path=request.url.path,
                query_params=dict(request.query_params)
            )
        
        # 包装send函数以捕获响应
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                # 完成请求追踪
                status_code = message.get("status", 200)
                RequestTracker.finish_tracking(None, status_code)
                
                # 完成性能追踪（如果启用）
                if self.include_performance and operation_id:
                    PerformanceTracker.finish_operation(
                        operation_id,
                        status_code=status_code
                    )
            
            await send(message)
        
        await self.app(scope, receive, send_wrapper)


# 装饰器函数
def traced_operation(operation_name: str = None):
    """追踪操作装饰器"""
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            name = operation_name or f"{func.__module__}.{func.__name__}"
            
            # 创建Span
            trace_context = TraceManager.get_current_trace()
            parent_span_id = trace_context['span_id'] if trace_context else None
            
            span = TraceManager.create_span(name, parent_span_id=parent_span_id)
            
            try:
                # 执行函数
                result = func(*args, **kwargs)
                
                # 完成Span
                span.status = "ok"
                return result
                
            except Exception as e:
                # 标记错误
                span.status = "error"
                span.tags['error'] = str(e)
                span.tags['error_type'] = type(e).__name__
                raise
                
        return wrapper
    return decorator


def performance_tracked(operation_name: str = None):
    """性能追踪装饰器"""
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            name = operation_name or f"{func.__module__}.{func.__name__}"
            
            # 开始性能追踪
            operation_id = PerformanceTracker.start_operation(name)
            
            try:
                # 执行函数
                result = func(*args, **kwargs)
                
                # 完成追踪
                PerformanceTracker.finish_operation(operation_id, success=True)
                
                return result
                
            except Exception as e:
                # 记录错误
                PerformanceTracker.finish_operation(
                    operation_id,
                    success=False,
                    error=str(e),
                    error_type=type(e).__name__
                )
                raise
                
        return wrapper
    return decorator


def request_context(**context_data):
    """请求上下文装饰器"""
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            # 更新请求上下文
            ContextManager.update_request_context(**context_data)
            
            # 执行函数
            try:
                return func(*args, **kwargs)
            finally:
                pass  # 保持上下文不变
                
        return wrapper
    return decorator


# 便捷函数
def get_request_id() -> Optional[str]:
    """获取当前请求ID"""
    request_data = RequestTracker.get_current_request()
    return request_data.get('request_id') if request_data else None


def get_trace_id() -> Optional[str]:
    """获取当前追踪ID"""
    trace_data = TraceManager.get_current_trace()
    return trace_data.get('trace_id') if trace_data else None


def get_user_id() -> Optional[int]:
    """获取当前用户ID"""
    request_data = RequestTracker.get_current_request()
    return request_data.get('user_id') if request_data else None