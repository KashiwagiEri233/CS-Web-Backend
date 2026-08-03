"""活动 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.base import TZModel

EVENT_STATUSES = {"upcoming", "ongoing", "ended"}
REGISTRATION_STATUSES = {"registered", "cancelled", "waitlisted"}
FIELD_TYPES = {"text", "textarea", "select", "checkbox"}

# 默认限制（与前端 DEFAULT_EVENT_SETTINGS 对齐；可经设置接口覆盖）
EVENT_LIMITS = {
    "title_max": 120,
    "desc_max": 500,
    "month_max": 8,
    "date_max": 32,
    "year_max": 8,
    "tag_max": 40,
    "tags_max": 10,
    "content_max": 10000,
    "default_capacity": 0,
    "max_capacity": 10000,
    "default_page_size": 50,
    "max_page_size": 200,
}


class RegistrationField(BaseModel):
    """报名自定义字段定义。"""

    key: str
    label: str
    type: str
    required: bool = False
    options: Optional[List[str]] = None

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in FIELD_TYPES:
            raise ValueError(f"自定义字段类型无效：{v}")
        return v

    @field_validator("key")
    @classmethod
    def _validate_key(cls, v: str) -> str:
        if v.startswith("_"):
            raise ValueError("自定义字段的 key 不能以下划线开头")
        return v


class EventInput(BaseModel):
    """创建/更新活动输入。"""

    month: Optional[str] = None
    date: Optional[str] = None
    title: str
    description: Optional[str] = None
    status: Optional[str] = "upcoming"
    year: Optional[str] = None
    topics: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    is_pinned: bool = False
    capacity: Optional[int] = 0
    content_markdown: Optional[str] = None
    registration_fields: Optional[List[RegistrationField]] = None
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        if len(v) > EVENT_LIMITS["title_max"]:
            raise ValueError(f"标题不能超过 {EVENT_LIMITS['title_max']} 字符")
        return v

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in EVENT_STATUSES:
            raise ValueError("状态必须为 upcoming / ongoing / ended")
        return v

    @field_validator("description")
    @classmethod
    def _validate_description(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) > EVENT_LIMITS["desc_max"]:
                raise ValueError(f"描述不能超过 {EVENT_LIMITS['desc_max']} 字符")
            return v or None
        return v

    @field_validator("month", "date", "year")
    @classmethod
    def _validate_dates(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            limit = {
                "month": EVENT_LIMITS["month_max"],
                "date": EVENT_LIMITS["date_max"],
                "year": EVENT_LIMITS["year_max"],
            }
            if len(v) > limit.get(cls.__name__ or "", EVENT_LIMITS["date_max"]):
                raise ValueError("日期字段过长")
            return v or None
        return v

    @field_validator("tags", "topics")
    @classmethod
    def _validate_tag_lists(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        if len(v) > EVENT_LIMITS["tags_max"]:
            raise ValueError(f"标签/主题数量不能超过 {EVENT_LIMITS['tags_max']}")
        if any(len(t) > EVENT_LIMITS["tag_max"] for t in v):
            raise ValueError(f"单个标签不能超过 {EVENT_LIMITS['tag_max']} 字符")
        return v

    @field_validator("capacity")
    @classmethod
    def _validate_capacity(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("活动容量不能为负数")
        return v

    @field_validator("content_markdown")
    @classmethod
    def _validate_content(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > EVENT_LIMITS["content_max"]:
            raise ValueError(f"活动详情不能超过 {EVENT_LIMITS['content_max']} 字符")
        return v


class EventOut(TZModel):
    """活动出参。"""

    id: int
    month: Optional[str] = None
    date: Optional[str] = None
    title: str
    description: Optional[str] = None
    status: Optional[str] = None
    year: Optional[str] = None
    topics: List[str] = []
    tags: List[str] = []
    is_pinned: bool = False
    capacity: int = 0
    content_markdown: Optional[str] = None
    registration_fields: List[Dict[str, Any]] = []
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    # 附加入口（列表/详情时按需填充）
    registered_count: Optional[int] = None


class EventRegistrationInput(BaseModel):
    """报名提交：自定义表单数据。"""

    form_data: Optional[Dict[str, str]] = None


class EventRegistrationOut(TZModel):
    """报名记录出参。"""

    id: int
    user_id: int
    event_id: int
    status: str
    form_data: Optional[Dict[str, str]] = None
    registered_at: datetime
    cancelled_at: Optional[datetime] = None


class EventCheckinOut(TZModel):
    """签到记录出参。"""

    id: int
    event_id: int
    registration_id: Optional[int] = None
    user_id: Optional[int] = None
    checkin_code: str
    checked_in_at: Optional[datetime] = None
    checked_in_by: Optional[int] = None
    created_at: datetime


class CheckinVerifyResult(BaseModel):
    """签到核销结果。"""

    ok: bool
    error: Optional[str] = None
    checkin: Optional[EventCheckinOut] = None
    display_name: Optional[str] = None


class EventSettingsIn(BaseModel):
    """活动设置批量更新。"""

    title_max: Optional[int] = Field(None, ge=0)
    desc_max: Optional[int] = Field(None, ge=0)
    month_max: Optional[int] = Field(None, ge=0)
    date_max: Optional[int] = Field(None, ge=0)
    year_max: Optional[int] = Field(None, ge=0)
    tag_max: Optional[int] = Field(None, ge=0)
    tags_max: Optional[int] = Field(None, ge=0)
    content_max: Optional[int] = Field(None, ge=0)
    default_capacity: Optional[int] = Field(None, ge=0)
    max_capacity: Optional[int] = Field(None, ge=0)
    default_page_size: Optional[int] = Field(None, ge=0)
    max_page_size: Optional[int] = Field(None, ge=0)


class BatchUpdateRequest(BaseModel):
    """批量操作：更新状态。"""

    event_ids: List[int]
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in EVENT_STATUSES:
            raise ValueError("状态必须为 upcoming / ongoing / ended")
        return v
