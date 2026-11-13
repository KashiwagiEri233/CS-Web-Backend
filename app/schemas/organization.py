"""组织 API schema：峰、成员、本人组织信息。"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import TZModel


class PeakOut(TZModel):
    id: int
    code: str
    name: str
    fantasy_name: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True
    archived_at: Optional[datetime] = None
    version: int = 1


class PeakCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=100)
    fantasy_name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)

    model_config = ConfigDict(extra="forbid")


class PeakUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    fantasy_name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None

    model_config = ConfigDict(extra="forbid")


class MemberOut(TZModel):
    id: int
    user_id: int
    username: str
    display_name: Optional[str] = None
    student_id: Optional[str] = None
    peak_id: Optional[int] = None
    peak_name: Optional[str] = None
    membership_status: str
    joined_at: Optional[datetime] = None
    left_at: Optional[datetime] = None
    version: int = 1


class MemberCreate(BaseModel):
    user_id: int = Field(gt=0)
    peak_id: Optional[int] = Field(None, gt=0)
    student_id: Optional[str] = Field(None, max_length=50)

    model_config = ConfigDict(extra="forbid")


class MemberUpdate(BaseModel):
    student_id: Optional[str] = Field(None, max_length=50)
    peak_id: Optional[int] = Field(None, gt=0)
    membership_status: Optional[str] = Field(
        None, pattern=r"^(active|suspended)$"
    )

    model_config = ConfigDict(extra="forbid")


class MemberMove(BaseModel):
    peak_id: Optional[int] = Field(None, gt=0)

    model_config = ConfigDict(extra="forbid")


class RoleBindingBrief(TZModel):
    role_name: str
    display_name: Optional[str] = None
    fantasy_display_name: Optional[str] = None
    scope_type: str
    scope_peak_id: Optional[int] = None


class OrganizationMeOut(TZModel):
    user_id: int
    username: str
    display_name: Optional[str] = None
    member: Optional[MemberOut] = None
    bindings: List[RoleBindingBrief] = Field(default_factory=list)
    authorization_version: int = 1
