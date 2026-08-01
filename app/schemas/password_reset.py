"""密码重置申请 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.core.validators import MAX_EMAIL_LENGTH
from app.schemas.base import TZModel


class ResetRequestCreate(BaseModel):
    """忘记密码：提交申请。"""

    email: EmailStr

    @field_validator("email")
    @classmethod
    def validate_email_length(cls, v: EmailStr) -> EmailStr:
        if len(str(v)) > MAX_EMAIL_LENGTH:
            raise ValueError(f"邮箱长度不能超过{MAX_EMAIL_LENGTH}个字符")
        return v


class ResetRequestResolve(BaseModel):
    """审批：批准/拒绝（附注可选）。"""

    note: Optional[str] = None
    model_config = ConfigDict(str_strip_whitespace=True)


class ResetRequestOut(TZModel):
    """申请出参。"""

    id: int
    email: EmailStr
    status: str
    admin_id: Optional[int] = None
    admin_note: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
