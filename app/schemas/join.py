"""入社申请 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.base import TZModel

JOIN_LIMITS = {
    "NAME_MAX": 20,
    "STUDENT_ID_MAX": 20,
    "MAJOR_MAX": 40,
    "REASON_MAX": 500,
    "QQ_MAX": 20,
    "PHONE_MAX": 20,
    "TAGS_MAX": 10,
    "TAG_MAX": 20,
}


class JoinApplicationInput(BaseModel):
    """提交入社申请（游客可提交；登录用户的 userId 由服务层注入）。"""

    applicant_name: str
    student_id: str
    major: str
    tech_tags: Optional[List[str]] = None
    reason: str
    contact_qq: Optional[str] = None
    contact_phone: Optional[str] = None
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("applicant_name", "student_id", "major", "reason")
    @classmethod
    def _required_trimmed(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("必填字段不能为空")
        return v

    @field_validator("applicant_name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if len(v) > JOIN_LIMITS["NAME_MAX"]:
            raise ValueError(f"姓名不能超过 {JOIN_LIMITS['NAME_MAX']} 字符")
        return v

    @field_validator("student_id")
    @classmethod
    def _validate_student_id(cls, v: str) -> str:
        if len(v) > JOIN_LIMITS["STUDENT_ID_MAX"]:
            raise ValueError(f"学号不能超过 {JOIN_LIMITS['STUDENT_ID_MAX']} 字符")
        return v

    @field_validator("major")
    @classmethod
    def _validate_major(cls, v: str) -> str:
        if len(v) > JOIN_LIMITS["MAJOR_MAX"]:
            raise ValueError(f"专业不能超过 {JOIN_LIMITS['MAJOR_MAX']} 字符")
        return v

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, v: str) -> str:
        if len(v) > JOIN_LIMITS["REASON_MAX"]:
            raise ValueError(f"申请理由不能超过 {JOIN_LIMITS['REASON_MAX']} 字符")
        return v

    @field_validator("contact_qq", "contact_phone")
    @classmethod
    def _validate_contact(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) > JOIN_LIMITS["QQ_MAX"]:
                raise ValueError("联系方式过长")
            return v or None
        return v

    @field_validator("tech_tags")
    @classmethod
    def _validate_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        if len(v) > JOIN_LIMITS["TAGS_MAX"]:
            raise ValueError(f"技术标签不能超过 {JOIN_LIMITS['TAGS_MAX']} 个")
        if any(len(t) > JOIN_LIMITS["TAG_MAX"] for t in v):
            raise ValueError(f"单个标签不能超过 {JOIN_LIMITS['TAG_MAX']} 字符")
        return v


class JoinApplicationOut(TZModel):
    """入社申请出参。"""

    id: int
    applicant_name: str
    student_id: str
    major: str
    tech_tags: List[str] = []
    reason: str
    contact_qq: Optional[str] = None
    contact_phone: Optional[str] = None
    user_id: Optional[int] = None
    status: str
    reviewed_by: Optional[int] = None
    review_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class JoinReviewRequest(BaseModel):
    """管理员审批。"""

    status: str  # approved | rejected
    review_note: Optional[str] = None
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        if v not in {"approved", "rejected"}:
            raise ValueError("status 必须为 approved 或 rejected")
        return v
