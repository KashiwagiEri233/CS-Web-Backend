"""
异常日志记录系统
提供结构化的异常日志记录、分析和存储功能
"""

import json
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_, or_

from app.core.loguru_logger import get_logger
from .base_exceptions import BaseAppException
from .response_models import ErrorContext

logger = get_logger("exception_logger")


class ExceptionLogger:
    """异常日志记录器"""
    
    def __init__(self):
        self.logger = get_logger("exception_logging")
    
    def log_exception(
        self,
        exception: Exception,
        request_context: Optional[Dict[str, Any]] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        记录异常信息
        
        Args:
            exception: 异常对象
            request_context: 请求上下文信息
            additional_data: 额外数据
            
        Returns:
            异常日志记录
        """
        # 获取基本信息
        exception_type = type(exception).__name__
        exception_message = str(exception)
        traceback_str = traceback.format_exc()
        
        # 构建日志记录
        log_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "exception_type": exception_type,
            "exception_message": exception_message,
            "traceback": traceback_str
        }
        
        # 添加应用异常的特殊信息
        if isinstance(exception, BaseAppException):
            log_record.update({
                "error_code": exception.error_code,
                "status_code": exception.status_code,
                "traceback_id": exception.traceback_id,
                "details": exception.details,
                "context": exception.context
            })
        
        # 添加请求上下文
        if request_context:
            log_record["request_context"] = request_context
        
        # 添加额外数据
        if additional_data:
            log_record["additional_data"] = additional_data
        
        # 记录日志
        self.logger.error(
            "异常发生",
            exception_type=exception_type,
            exception_message=exception_message,
            error_code=log_record.get("error_code"),
            status_code=log_record.get("status_code"),
            traceback_id=log_record.get("traceback_id"),
            request_id=request_context.get("request_id") if request_context else None,
            user_id=request_context.get("user_id") if request_context else None,
            endpoint=request_context.get("endpoint") if request_context else None,
            exc_info=True
        )
        
        return log_record
    
    def log_validation_error(
        self,
        errors: List[Dict[str, Any]],
        request_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        记录验证错误
        
        Args:
            errors: 验证错误列表
            request_context: 请求上下文信息
            
        Returns:
            验证错误日志记录
        """
        log_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "error_type": "validation_error",
            "errors": errors
        }
        
        # 添加请求上下文
        if request_context:
            log_record["request_context"] = request_context
        
        # 记录日志
        self.logger.warning(
            "验证错误",
            error_count=len(errors),
            errors=errors,
            request_id=request_context.get("request_id") if request_context else None,
            endpoint=request_context.get("endpoint") if request_context else None
        )
        
        return log_record


class ExceptionAnalyzer:
    """异常分析器"""
    
    def __init__(self):
        self.logger = get_logger("exception_analyzer")
    
    def analyze_exception_patterns(
        self,
        logs: List[Dict[str, Any]],
        time_window_hours: int = 24
    ) -> Dict[str, Any]:
        """
        分析异常模式
        
        Args:
            logs: 异常日志记录列表
            time_window_hours: 时间窗口（小时）
            
        Returns:
            异常模式分析结果
        """
        if not logs:
            return {"message": "没有可分析的异常日志"}
        
        # 按异常类型分组统计
        exception_counts = {}
        error_codes = {}
        status_codes = {}
        endpoints = {}
        user_ids = {}
        
        recent_logs = []
        cutoff_time = datetime.utcnow().timestamp() - (time_window_hours * 3600)
        
        for log in logs:
            # 检查时间窗口
            log_time = datetime.fromisoformat(log["timestamp"]).timestamp()
            if log_time >= cutoff_time:
                recent_logs.append(log)
            
            # 统计异常类型
            exception_type = log.get("exception_type", "unknown")
            exception_counts[exception_type] = exception_counts.get(exception_type, 0) + 1
            
            # 统计错误代码
            error_code = log.get("error_code")
            if error_code:
                error_codes[error_code] = error_codes.get(error_code, 0) + 1
            
            # 统计状态码
            status_code = log.get("status_code")
            if status_code:
                status_codes[status_code] = status_codes.get(status_code, 0) + 1
            
            # 统计端点
            request_context = log.get("request_context", {})
            endpoint = request_context.get("endpoint")
            if endpoint:
                endpoints[endpoint] = endpoints.get(endpoint, 0) + 1
            
            # 统计用户
            user_id = request_context.get("user_id")
            if user_id:
                user_ids[user_id] = user_ids.get(user_id, 0) + 1
        
        # 排序获取最常见的异常
        top_exceptions = sorted(exception_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        top_error_codes = sorted(error_codes.items(), key=lambda x: x[1], reverse=True)[:10]
        top_endpoints = sorted(endpoints.items(), key=lambda x: x[1], reverse=True)[:10]
        top_users = sorted(user_ids.items(), key=lambda x: x[1], reverse=True)[:10]
        
        return {
            "time_window_hours": time_window_hours,
            "total_exceptions": len(logs),
            "recent_exceptions": len(recent_logs),
            "top_exception_types": top_exceptions,
            "top_error_codes": top_error_codes,
            "status_codes": status_codes,
            "top_endpoints": top_endpoints,
            "top_users": top_users
        }
    
    def detect_anomalies(
        self,
        logs: List[Dict[str, Any]],
        baseline_window_hours: int = 168,  # 一周
        current_window_hours: int = 1      # 最近一小时
    ) -> Dict[str, Any]:
        """
        检测异常模式
        
        Args:
            logs: 异常日志记录列表
            baseline_window_hours: 基准时间窗口（小时）
            current_window_hours: 当前时间窗口（小时）
            
        Returns:
            异常检测结果
        """
        if not logs:
            return {"message": "没有可分析的异常日志"}
        
        # 分割时间窗口
        baseline_cutoff = datetime.utcnow().timestamp() - (baseline_window_hours * 3600)
        current_cutoff = datetime.utcnow().timestamp() - (current_window_hours * 3600)
        
        baseline_logs = []
        current_logs = []
        
        for log in logs:
            log_time = datetime.fromisoformat(log["timestamp"]).timestamp()
            if log_time >= current_cutoff:
                current_logs.append(log)
            elif log_time >= baseline_cutoff:
                baseline_logs.append(log)
        
        # 计算基准平均值
        baseline_rate = len(baseline_logs) / (baseline_window_hours - current_window_hours)
        current_rate = len(current_logs) / current_window_hours
        
        # 检测异常
        anomalies = []
        
        # 异常率异常检测
        if baseline_rate > 0:
            rate_increase = (current_rate - baseline_rate) / baseline_rate
            if rate_increase > 0.5:  # 50%增长
                anomalies.append({
                    "type": "异常率增加",
                    "severity": "high" if rate_increase > 1.0 else "medium",
                    "baseline_rate": baseline_rate,
                    "current_rate": current_rate,
                    "increase_percentage": f"{rate_increase * 100:.1f}%"
                })
        
        # 错误代码异常检测
        baseline_error_counts = {}
        current_error_counts = {}
        
        for log in baseline_logs:
            error_code = log.get("error_code")
            if error_code:
                baseline_error_counts[error_code] = baseline_error_counts.get(error_code, 0) + 1
        
        for log in current_logs:
            error_code = log.get("error_code")
            if error_code:
                current_error_counts[error_code] = current_error_counts.get(error_code, 0) + 1
        
        # 检测新的错误代码
        for error_code, count in current_error_counts.items():
            if error_code not in baseline_error_counts and count >= 3:  # 新出现的错误
                anomalies.append({
                    "type": "新错误代码",
                    "error_code": error_code,
                    "count": count,
                    "severity": "medium"
                })
        
        return {
            "anomalies": anomalies,
            "baseline_period": f"{baseline_window_hours - current_window_hours}小时",
            "current_period": f"{current_window_hours}小时",
            "baseline_logs": len(baseline_logs),
            "current_logs": len(current_logs),
            "has_anomalies": len(anomalies) > 0
        }


class ExceptionMetrics:
    """异常指标收集器"""
    
    def __init__(self):
        self.logger = get_logger("exception_metrics")
    
    def collect_metrics(
        self,
        logs: List[Dict[str, Any]],
        time_window_hours: int = 24
    ) -> Dict[str, Any]:
        """
        收集异常指标
        
        Args:
            logs: 异常日志记录列表
            time_window_hours: 时间窗口（小时）
            
        Returns:
            异常指标
        """
        if not logs:
            return {"message": "没有异常日志"}
        
        # 过滤时间窗口
        cutoff_time = datetime.utcnow().timestamp() - (time_window_hours * 3600)
        window_logs = [
            log for log in logs
            if datetime.fromisoformat(log["timestamp"]).timestamp() >= cutoff_time
        ]
        
        # 基础指标
        total_exceptions = len(window_logs)
        
        # 按状态码分组
        status_4xx = 0
        status_5xx = 0
        status_other = 0
        
        # 按异常类型分组
        app_exceptions = 0
        http_exceptions = 0
        validation_exceptions = 0
        database_exceptions = 0
        other_exceptions = 0
        
        # 按用户分组
        user_exceptions = {}
        anonymous_exceptions = 0
        
        for log in window_logs:
            # 状态码统计
            status_code = log.get("status_code")
            if status_code:
                if 400 <= status_code < 500:
                    status_4xx += 1
                elif 500 <= status_code < 600:
                    status_5xx += 1
                else:
                    status_other += 1
            
            # 异常类型统计
            exception_type = log.get("exception_type", "")
            error_code = log.get("error_code", "")
            
            if "App" in exception_type or error_code:
                app_exceptions += 1
            elif "HTTP" in exception_type:
                http_exceptions += 1
            elif "validation" in error_code.lower() or "ValidationError" in exception_type:
                validation_exceptions += 1
            elif "database" in error_code.lower() or "SQL" in exception_type:
                database_exceptions += 1
            else:
                other_exceptions += 1
            
            # 用户统计
            request_context = log.get("request_context", {})
            user_id = request_context.get("user_id")
            if user_id:
                user_exceptions[user_id] = user_exceptions.get(user_id, 0) + 1
            else:
                anonymous_exceptions += 1
        
        # 计算错误率
        error_rate_4xx = status_4xx / total_exceptions if total_exceptions > 0 else 0
        error_rate_5xx = status_5xx / total_exceptions if total_exceptions > 0 else 0
        
        return {
            "time_window_hours": time_window_hours,
            "total_exceptions": total_exceptions,
            "error_rates": {
                "client_error_rate_4xx": round(error_rate_4xx * 100, 2),
                "server_error_rate_5xx": round(error_rate_5xx * 100, 2),
                "other_error_rate": round((1 - error_rate_4xx - error_rate_5xx) * 100, 2)
            },
            "exception_types": {
                "application_exceptions": app_exceptions,
                "http_exceptions": http_exceptions,
                "validation_exceptions": validation_exceptions,
                "database_exceptions": database_exceptions,
                "other_exceptions": other_exceptions
            },
            "user_metrics": {
                "total_users_with_exceptions": len(user_exceptions),
                "top_users_with_exceptions": sorted(user_exceptions.items(), key=lambda x: x[1], reverse=True)[:5],
                "anonymous_exceptions": anonymous_exceptions
            }
        }


# 全局实例
exception_logger = ExceptionLogger()
exception_analyzer = ExceptionAnalyzer()
exception_metrics = ExceptionMetrics()