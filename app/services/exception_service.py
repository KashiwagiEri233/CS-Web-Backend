"""
异常管理服务
提供异常记录、分析、模式识别和告警功能
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions.base_exceptions import BaseAppException
from app.core.exceptions.exception_logging import (
    ExceptionLogger,
    ExceptionAnalyzer,
    ExceptionMetricsCollector,
)
from app.repositories.exception_log_repo import (
    ExceptionLogRepository,
    ExceptionPatternRepository,
    ExceptionAlertRepository,
    ExceptionMetricsRepository,
)
from app.models.exception_log import (
    ExceptionLog,
    ExceptionPattern,
    ExceptionAlert,
    ExceptionMetrics,
)


class ExceptionService:
    """异常管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = ExceptionLogger()
        self.analyzer = ExceptionAnalyzer()
        self.metrics_collector = ExceptionMetricsCollector()

        # 仓储
        self.log_repo = ExceptionLogRepository(db)
        self.pattern_repo = ExceptionPatternRepository(db)
        self.alert_repo = ExceptionAlertRepository(db)
        self.metrics_repo = ExceptionMetricsRepository(db)

    async def record_exception(
        self,
        exception: Exception,
        request_context: Optional[Dict[str, Any]] = None,
        additional_data: Optional[Dict[str, Any]] = None,
    ) -> ExceptionLog:
        """
        记录异常到数据库和日志系统

        Args:
            exception: 异常对象
            request_context: 请求上下文
            additional_data: 额外数据

        Returns:
            创建的异常日志记录
        """
        # 记录到日志系统
        log_record = self.logger.log_exception(
            exception, request_context, additional_data
        )

        # 准备数据库记录数据
        exception_data = {
            "traceback_id": log_record.get("traceback_id"),
            "exception_type": log_record.get("exception_type"),
            "error_code": log_record.get("error_code"),
            "exception_message": log_record.get("exception_message"),
            "status_code": log_record.get("status_code"),
            "method": request_context.get("method") if request_context else None,
            "endpoint": request_context.get("endpoint") if request_context else None,
            "request_id": (
                request_context.get("request_id") if request_context else None
            ),
            "user_id": request_context.get("user_id") if request_context else None,
            "ip_address": (
                request_context.get("ip_address") if request_context else None
            ),
            "user_agent": (
                request_context.get("user_agent") if request_context else None
            ),
            "details": log_record.get("details"),
            "traceback": log_record.get("traceback"),
            "context": log_record.get("context"),
            "severity": self._determine_severity(exception),
            "priority": self._determine_priority(exception),
        }

        # 如果是应用异常，设置特定的严重程度和优先级
        if isinstance(exception, BaseAppException):
            exception_data["severity"] = getattr(exception, "severity", "medium")
            exception_data["priority"] = getattr(exception, "priority", "normal")

        # 保存到数据库
        exception_log = await self.log_repo.create_exception_log(exception_data)

        # 异步处理异常模式检测和告警
        await self._process_exception_patterns(exception_log)

        return exception_log

    async def record_validation_error(
        self,
        errors: List[Dict[str, Any]],
        request_context: Optional[Dict[str, Any]] = None,
    ) -> ExceptionLog:
        """
        记录验证错误

        Args:
            errors: 验证错误列表
            request_context: 请求上下文

        Returns:
            创建的异常日志记录
        """
        # 记录到日志系统
        log_record = self.logger.log_validation_error(errors, request_context)

        # 准备数据库记录数据
        exception_data = {
            "traceback_id": str(uuid4()),
            "exception_type": "ValidationError",
            "error_code": "VALIDATION_FAILED",
            "exception_message": "数据验证失败",
            "status_code": 422,
            "method": request_context.get("method") if request_context else None,
            "endpoint": request_context.get("endpoint") if request_context else None,
            "request_id": (
                request_context.get("request_id") if request_context else None
            ),
            "user_id": request_context.get("user_id") if request_context else None,
            "ip_address": (
                request_context.get("ip_address") if request_context else None
            ),
            "user_agent": (
                request_context.get("user_agent") if request_context else None
            ),
            "details": {"validation_errors": errors},
            "context": request_context,
            "severity": "low",
            "priority": "low",
        }

        # 保存到数据库
        exception_log = await self.log_repo.create_exception_log(exception_data)

        return exception_log

    async def get_exception_statistics(
        self, time_window_hours: int = 24
    ) -> Dict[str, Any]:
        """
        获取异常统计信息

        Args:
            time_window_hours: 时间窗口（小时）

        Returns:
            统计信息
        """
        return await self.log_repo.get_exception_statistics(time_window_hours)

    async def analyze_exception_patterns(
        self, time_window_hours: int = 24
    ) -> Dict[str, Any]:
        """
        分析异常模式

        Args:
            time_window_hours: 时间窗口（小时）

        Returns:
            异常模式分析结果
        """
        # 获取异常日志
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(hours=time_window_hours)

        exception_logs, _ = await self.log_repo.get_exception_logs(
            start_date=start_date,
            end_date=end_date,
            limit=1000,  # 限制获取数量以提高性能
        )

        # 转换为日志记录格式
        log_records = [log.to_dict() for log in exception_logs]

        # 分析模式
        return self.analyzer.analyze_exception_patterns(log_records, time_window_hours)

    async def detect_anomalies(
        self, baseline_window_hours: int = 168, current_window_hours: int = 1
    ) -> Dict[str, Any]:
        """
        检测异常模式

        Args:
            baseline_window_hours: 基准时间窗口（小时）
            current_window_hours: 当前时间窗口（小时）

        Returns:
            异常检测结果
        """
        # 获取异常日志
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(hours=baseline_window_hours)

        exception_logs, _ = await self.log_repo.get_exception_logs(
            start_date=start_date,
            end_date=end_date,
            limit=5000,  # 限制获取数量以提高性能
        )

        # 转换为日志记录格式
        log_records = [log.to_dict() for log in exception_logs]

        # 检测异常
        return self.analyzer.detect_anomalies(
            log_records, baseline_window_hours, current_window_hours
        )

    async def collect_metrics(self, time_window_hours: int = 24) -> Dict[str, Any]:
        """
        收集异常指标

        Args:
            time_window_hours: 时间窗口（小时）

        Returns:
            异常指标
        """
        # 获取异常日志
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(hours=time_window_hours)

        exception_logs, _ = await self.log_repo.get_exception_logs(
            start_date=start_date,
            end_date=end_date,
            limit=5000,  # 限制获取数量以提高性能
        )

        # 转换为日志记录格式
        log_records = [log.to_dict() for log in exception_logs]

        # 收集指标
        return self.metrics_collector.collect_metrics(log_records, time_window_hours)

    async def store_metrics(
        self, time_window: str, window_start: datetime, window_end: datetime
    ) -> ExceptionMetrics:
        """
        存储异常指标

        Args:
            time_window: 时间窗口
            window_start: 窗口开始时间
            window_end: 窗口结束时间

        Returns:
            创建的指标记录
        """
        # 计算时间窗口的小时数
        hours = int((window_end - window_start).total_seconds() / 3600)

        # 收集指标
        metrics_data = await self.collect_metrics(hours)

        # 检查是否已存在相同时间窗口的指标
        existing_metrics = await self.metrics_repo.get_metrics_by_time_window(
            time_window, window_start, window_end
        )

        if existing_metrics:
            return existing_metrics

        # 准备指标数据
        metrics_record_data = {
            "time_window": time_window,
            "window_start": window_start,
            "window_end": window_end,
            "total_exceptions": metrics_data.get("total_exceptions", 0),
            "unique_tracebacks": 1,  # 简化处理，实际应从metrics_data获取
            "client_errors_4xx": metrics_data.get("exception_types", {}).get(
                "validation_exceptions", 0
            ),
            "server_errors_5xx": metrics_data.get("exception_types", {}).get(
                "application_exceptions", 0
            )
            + metrics_data.get("exception_types", {}).get("database_exceptions", 0),
            "application_exceptions": metrics_data.get("exception_types", {}).get(
                "application_exceptions", 0
            ),
            "http_exceptions": metrics_data.get("exception_types", {}).get(
                "http_exceptions", 0
            ),
            "validation_exceptions": metrics_data.get("exception_types", {}).get(
                "validation_exceptions", 0
            ),
            "database_exceptions": metrics_data.get("exception_types", {}).get(
                "database_exceptions", 0
            ),
            "exceptions_from_authenticated_users": metrics_data.get(
                "user_metrics", {}
            ).get("total_users_with_exceptions", 0),
            "exceptions_from_anonymous_users": metrics_data.get("user_metrics", {}).get(
                "anonymous_exceptions", 0
            ),
            "top_endpoints": metrics_data.get("top_endpoints", []),
            "top_error_codes": metrics_data.get("top_error_codes", []),
        }

        # 保存到数据库
        return await self.metrics_repo.create_metrics(metrics_record_data)

    async def resolve_exception(
        self, log_id: int, resolved_by: str, resolution_notes: Optional[str] = None
    ) -> Optional[ExceptionLog]:
        """
        解决异常

        Args:
            log_id: 日志ID
            resolved_by: 解决人
            resolution_notes: 解决备注

        Returns:
            更新后的异常日志或None
        """
        return await self.log_repo.resolve_exception_log(
            log_id, resolved_by, resolution_notes
        )

    async def get_exception_logs(
        self,
        skip: int = 0,
        limit: int = 100,
        exception_type: Optional[str] = None,
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
        user_id: Optional[str] = None,
        is_resolved: Optional[bool] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> Tuple[List[ExceptionLog], int]:
        """
        获取异常日志列表

        Args:
            skip: 跳过记录数
            limit: 限制记录数
            exception_type: 异常类型筛选
            error_code: 错误代码筛选
            status_code: 状态码筛选
            user_id: 用户ID筛选
            is_resolved: 是否已解决筛选
            start_date: 开始日期
            end_date: 结束日期
            sort_by: 排序字段
            sort_order: 排序方向

        Returns:
            异常日志列表和总数
        """
        return await self.log_repo.get_exception_logs(
            skip=skip,
            limit=limit,
            exception_type=exception_type,
            error_code=error_code,
            status_code=status_code,
            user_id=user_id,
            is_resolved=is_resolved,
            start_date=start_date,
            end_date=end_date,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_active_alerts(self) -> List[ExceptionAlert]:
        """获取所有活跃的告警"""
        return await self.alert_repo.get_open_alerts()

    async def acknowledge_alert(
        self, alert_id: int, acknowledged_by: str
    ) -> Optional[ExceptionAlert]:
        """
        确认告警

        Args:
            alert_id: 告警ID
            acknowledged_by: 确认人

        Returns:
            更新后的告警或None
        """
        return await self.alert_repo.acknowledge_alert(alert_id, acknowledged_by)

    async def resolve_alert(
        self, alert_id: int, resolved_by: str
    ) -> Optional[ExceptionAlert]:
        """
        解决告警

        Args:
            alert_id: 告警ID
            resolved_by: 解决人

        Returns:
            更新后的告警或None
        """
        return await self.alert_repo.resolve_alert(alert_id, resolved_by)

    def _determine_severity(self, exception: Exception) -> str:
        """确定异常严重程度"""
        if isinstance(exception, BaseAppException):
            # 应用异常使用默认的medium
            return "medium"

        exception_type = type(exception).__name__

        # 根据异常类型确定严重程度
        if exception_type in ["ValidationError", "ValueError"]:
            return "low"
        elif exception_type in ["AuthenticationException", "AuthorizationException"]:
            return "medium"
        elif exception_type in ["DatabaseException", "ExternalServiceException"]:
            return "high"
        else:
            return "medium"

    def _determine_priority(self, exception: Exception) -> str:
        """确定异常优先级"""
        if isinstance(exception, BaseAppException):
            # 应用异常使用默认的normal
            return "normal"

        exception_type = type(exception).__name__

        # 根据异常类型确定优先级
        if exception_type in ["ValidationError", "ValueError"]:
            return "low"
        elif exception_type in ["AuthenticationException", "AuthorizationException"]:
            return "normal"
        elif exception_type in ["DatabaseException", "ExternalServiceException"]:
            return "high"
        else:
            return "normal"

    async def _process_exception_patterns(self, exception_log: ExceptionLog) -> None:
        """处理异常模式检测和告警（异步）"""
        try:
            # 检查是否匹配已知模式
            active_patterns = await self.pattern_repo.get_active_patterns()

            matched_pattern = None
            for pattern in active_patterns:
                if self._matches_pattern(exception_log, pattern):
                    matched_pattern = pattern
                    await self.pattern_repo.increment_pattern_occurrence(pattern.id)
                    break

            # 如果没有匹配的模式，可能需要创建新模式（可选）
            if not matched_pattern and self._should_create_pattern(exception_log):
                await self._create_exception_pattern(exception_log)

            # 检查是否需要创建告警
            if (
                matched_pattern
                and matched_pattern.occurrence_count >= matched_pattern.alert_threshold
            ):
                await self._create_alert(exception_log, matched_pattern)
        except Exception as e:
            # 记录模式处理错误，但不影响主流程
            self.logger.logger.error(
                "处理异常模式失败",
                error=str(e),
                traceback_id=exception_log.traceback_id,
            )

    def _matches_pattern(
        self, exception_log: ExceptionLog, pattern: ExceptionPattern
    ) -> bool:
        """检查异常日志是否匹配模式"""
        # 检查异常类型
        if (
            pattern.exception_type
            and exception_log.exception_type != pattern.exception_type
        ):
            return False

        # 检查错误代码
        if pattern.error_code and exception_log.error_code != pattern.error_code:
            return False

        # 检查端点模式
        if pattern.endpoint_pattern and exception_log.endpoint:
            import re

            if not re.match(pattern.endpoint_pattern, exception_log.endpoint):
                return False

        # 检查用户ID模式
        if pattern.user_id_pattern and exception_log.user_id:
            import re

            if not re.match(pattern.user_id_pattern, exception_log.user_id):
                return False

        return True

    def _should_create_pattern(self, exception_log: ExceptionLog) -> bool:
        """判断是否应该创建新模式"""
        # 简单逻辑：如果是5xx错误，则可能需要创建模式
        if exception_log.status_code and 500 <= exception_log.status_code < 600:
            return True
        return False

    async def _create_exception_pattern(self, exception_log: ExceptionLog) -> None:
        """创建异常模式"""
        pattern_data = {
            "pattern_name": f"Pattern_{exception_log.exception_type}_{exception_log.traceback_id[:8]}",
            "pattern_type": "auto_generated",
            "exception_type": exception_log.exception_type,
            "error_code": exception_log.error_code,
            "endpoint_pattern": exception_log.endpoint,
            "occurrence_count": 1,
            "last_occurrence": datetime.now(timezone.utc),
            "is_active": True,
            "alert_threshold": 10,
        }

        await self.pattern_repo.create_pattern(pattern_data)

    async def _create_alert(
        self, exception_log: ExceptionLog, pattern: ExceptionPattern
    ) -> None:
        """创建告警"""
        # 检查是否已存在相同模式的未解决告警
        existing_alerts = await self.alert_repo.get_open_alerts()
        for alert in existing_alerts:
            if alert.pattern_id == pattern.id:
                return  # 已存在未解决的告警

        # 创建新告警
        alert_data = {
            "alert_id": str(uuid4()),
            "alert_type": "pattern_threshold",
            "severity": (
                "high"
                if pattern.occurrence_count >= pattern.alert_threshold * 2
                else "medium"
            ),
            "title": f"异常模式告警: {pattern.pattern_name}",
            "description": f"异常模式 '{pattern.pattern_name}' 出现次数已达到阈值 {pattern.alert_threshold}",
            "pattern_id": pattern.id,
            "exception_log_ids": [exception_log.id],
            "status": "open",
        }

        await self.alert_repo.create_alert(alert_data)
