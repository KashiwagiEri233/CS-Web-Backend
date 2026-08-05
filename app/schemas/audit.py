"""审计日志 API schema。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class AuditLogItem(BaseModel):
    """单条审计日志出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: Optional[int] = None
    actor_username: Optional[str] = None
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: Optional[str] = Field(
        default=None,
        description="ISO 时间（本地时区展示）",
    )


class CreateAuditLogRequest(BaseModel):
    """创建审计日志入参（B1 阶段2：前端 logAdminAction 改走后端）。

    操作者身份（actor）由当前已认证用户推导，不信任客户端传入，避免伪造。
    """

    action: str = Field(..., min_length=1, max_length=128, description="动作标识，如 user.create")
    resource_type: str = Field(
        ..., min_length=1, max_length=64, description="资源类型，如 user/role/event"
    )
    resource_id: Optional[str] = Field(
        default=None, max_length=128, description="资源 ID（字符串化）"
    )
    detail: Optional[Dict[str, Any]] = Field(
        default=None, description="操作细节（敏感字段应由调用方脱敏）"
    )
