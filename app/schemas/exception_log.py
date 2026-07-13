"""异常日志 API 出参 schema。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExceptionLogItem(BaseModel):
    """单条异常日志（列表/详情共用精简字段）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    traceback_id: str
    exception_type: str
    error_code: Optional[str] = None
    exception_message: str
    status_code: Optional[int] = None
    method: Optional[str] = None
    endpoint: Optional[str] = None
    request_id: Optional[str] = None
    user_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    traceback: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    is_resolved: bool = False
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None
    severity: Optional[str] = None
    priority: Optional[str] = None


class ExceptionLogResolveResponse(BaseModel):
    message: str = Field(default="异常已解决")
    log: ExceptionLogItem
