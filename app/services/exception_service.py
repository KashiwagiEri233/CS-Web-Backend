"""
异常管理服务
只保留核心能力：记录异常、查询日志、标记解决。
模式识别/告警/指标采集已移除——如需 APM 建议接入 Sentry/Datadog。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ErrorCode
from app.core.exceptions.exception_logging import ExceptionLogger
from app.core.timezone import now_utc
from app.models.exception_log import ExceptionLog
from app.repositories.exception_log_repo import ExceptionLogRepository


class ExceptionService:
    """异常管理服务（精简版：记录 + 查询 + 解决）"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = ExceptionLogger()
        self.log_repo = ExceptionLogRepository(db)

    async def record_exception(
        self,
        exception: Exception,
        request_context: Optional[Dict[str, Any]] = None,
        additional_data: Optional[Dict[str, Any]] = None,
    ) -> ExceptionLog:
        """记录异常到数据库和日志系统。"""
        # 先写日志（loguru），即使 DB 失败也有记录
        log_record = self.logger.log_exception(
            exception=exception,
            request_context=request_context,
            additional_data=additional_data,
        )

        # 构建异常日志数据
        exception_log_data = {
            "traceback_id": log_record.get("traceback_id", ""),
            "exception_type": log_record.get(
                "exception_type", type(exception).__name__
            ),
            "error_code": log_record.get("error_code"),
            "exception_message": log_record.get("exception_message", str(exception)),
            "status_code": log_record.get("status_code"),
            "method": request_context.get("method") if request_context else None,
            "endpoint": request_context.get("endpoint") if request_context else None,
            "request_id": (
                request_context.get("request_id") if request_context else None
            ),
            "user_id": (
                str(request_context.get("user_id"))
                if request_context and request_context.get("user_id")
                else None
            ),
            "ip_address": (
                request_context.get("ip_address") if request_context else None
            ),
            "user_agent": (
                request_context.get("user_agent") if request_context else None
            ),
            "traceback": log_record.get("traceback"),
            "details": log_record.get("details"),
            "context": log_record.get("context"),
            "severity": self._determine_severity(
                exception, log_record.get("status_code")
            ),
            "priority": self._determine_priority(
                exception, log_record.get("status_code")
            ),
        }

        log = await self.log_repo.create_exception_log(exception_log_data)
        await self.db.commit()
        return log

    async def record_validation_error(
        self,
        errors: List[Dict[str, Any]],
        request_context: Optional[Dict[str, Any]] = None,
    ) -> ExceptionLog:
        """记录验证错误到数据库和日志系统。"""
        log_record = self.logger.log_validation_error(
            errors=errors,
            request_context=request_context,
        )

        exception_log_data = {
            "traceback_id": log_record.get(
                "traceback_id", now_utc().strftime("%Y%m%d%H%M%S%f")
            ),
            "exception_type": "ValidationError",
            "error_code": ErrorCode.Validation.VALIDATION_FAILED,
            "exception_message": f"验证失败: {len(errors)} 个错误",
            "status_code": 422,
            "method": request_context.get("method") if request_context else None,
            "endpoint": request_context.get("endpoint") if request_context else None,
            "request_id": (
                request_context.get("request_id") if request_context else None
            ),
            "user_id": (
                str(request_context.get("user_id"))
                if request_context and request_context.get("user_id")
                else None
            ),
            "ip_address": (
                request_context.get("ip_address") if request_context else None
            ),
            "user_agent": (
                request_context.get("user_agent") if request_context else None
            ),
            "details": {"errors": errors},
            "severity": "low",
            "priority": "normal",
        }

        log = await self.log_repo.create_exception_log(exception_log_data)
        await self.db.commit()
        return log

    async def get_exception_logs(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters,
    ) -> Tuple[List[ExceptionLog], int]:
        """查询异常日志列表。"""
        return await self.log_repo.get_exception_logs(skip=skip, limit=limit, **filters)

    async def get_exception_log(self, log_id: int) -> Optional[ExceptionLog]:
        """获取单条异常日志。"""
        return await self.log_repo.get_exception_log_by_id(log_id)

    async def resolve_exception(
        self,
        log_id: int,
        resolved_by: str,
        resolution_notes: Optional[str] = None,
    ) -> Optional[ExceptionLog]:
        """标记异常为已解决。"""
        log = await self.log_repo.resolve_exception_log(
            log_id=log_id,
            resolved_by=resolved_by,
            resolution_notes=resolution_notes,
        )
        if log is not None:
            await self.db.commit()
        return log

    async def purge_before(self, cutoff: datetime) -> int:
        """清理保留期以前的异常日志并提交事务。"""
        deleted = await self.log_repo.delete_before(cutoff)
        await self.db.commit()
        return deleted

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _determine_severity(exception: Exception, status_code: Optional[int]) -> str:
        """根据异常类型和状态码推断严重程度。

        严重度由高到低：critical(5xx) > medium(4xx) > low(其余，如无状态码的内部异常)。
        """
        if status_code and status_code >= 500:
            return "critical"
        if status_code and status_code >= 400:
            return "medium"
        return "low"

    @staticmethod
    def _determine_priority(exception: Exception, status_code: Optional[int]) -> str:
        """根据异常类型和状态码推断优先级。"""
        if status_code and status_code >= 500:
            return "high"
        return "normal"
