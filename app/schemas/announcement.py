"""公告 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.base import TZModel

ANNOUNCEMENT_LIMITS = {
    "TITLE_MAX": 100,
    "CONTENT_MAX": 2000,
}


class AnnouncementInput(BaseModel):
    """创建/更新公告输入。"""

    title: str
    content: Optional[str] = None
    level: str = "info"
    is_dismissible: bool = True
    priority: int = 0
    expires_at: Optional[datetime] = None
    target_roles: Optional[List[str]] = None
    is_active: bool = True
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        if len(v) > ANNOUNCEMENT_LIMITS["TITLE_MAX"]:
            raise ValueError(f"标题不能超过 {ANNOUNCEMENT_LIMITS['TITLE_MAX']} 字符")
        return v

    @field_validator("content")
    @classmethod
    def _validate_content(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) > ANNOUNCEMENT_LIMITS["CONTENT_MAX"]:
                raise ValueError(
                    f"内容不能超过 {ANNOUNCEMENT_LIMITS['CONTENT_MAX']} 字符"
                )
            return v or None
        return v

    @field_validator("level")
    @classmethod
    def _validate_level(cls, v: str) -> str:
        if v not in {"info", "success", "warning", "danger"}:
            raise ValueError("level 必须为 info/success/warning/danger")
        return v


class AnnouncementOut(TZModel):
    """公告出参。"""

    id: int
    title: str
    content: Optional[str] = None
    level: str
    is_active: bool
    is_dismissible: bool
    priority: int
    expires_at: Optional[datetime] = None
    target_roles: Optional[List[str]] = None
    created_by: int
    created_at: datetime
    updated_at: datetime
