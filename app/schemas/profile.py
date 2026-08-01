"""个人资料（profile）入参/出参 schema。

字段限制与前端一致（src/modules/user/types/index.ts）：
DISPLAY_NAME_MAX=32 / BIO_MAX=200 / URL_MAX=500，仅 http/https。
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.schemas.auth import UserOut
from app.schemas.base import TZModel

DISPLAY_NAME_MAX = 32
BIO_MAX = 200
URL_MAX = 500


def _is_valid_http_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


class ProfileUpdate(BaseModel):
    """资料可编辑字段（显式传入的字段才更新；空字符串归一为 None）。"""

    display_name: Optional[str] = None
    bio: Optional[str] = None
    github_url: Optional[str] = None
    website_url: Optional[str] = None
    tech_tags: Optional[List[str]] = None
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("display_name", "bio", "github_url", "website_url", mode="after")
    @classmethod
    def _normalize_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            return v or None
        return v

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > DISPLAY_NAME_MAX:
            raise ValueError(f"显示名不能超过 {DISPLAY_NAME_MAX} 个字符")
        return v

    @field_validator("bio")
    @classmethod
    def _validate_bio(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > BIO_MAX:
            raise ValueError(f"个人简介不能超过 {BIO_MAX} 个字符")
        return v

    @field_validator("github_url", "website_url")
    @classmethod
    def _validate_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if len(v) > URL_MAX:
                raise ValueError("链接过长")
            if not _is_valid_http_url(v):
                raise ValueError("链接格式不正确（仅支持 http/https）")
        return v


class ChangePasswordRequest(BaseModel):
    """自助改密。"""

    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _validate_new_password(cls, v: str) -> str:
        from app.core.validators import validate_password_strength

        is_valid, error_msg = validate_password_strength(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v


class AvatarPresetRequest(BaseModel):
    """设置预设头像。"""

    preset_id: int


class ActivityParticipationOut(TZModel):
    """用户主页活动参与记录。"""

    id: int
    activity_title: str
    activity_date: str
    role: Optional[str] = None
    created_at: datetime


class ProfileResponse(TZModel):
    """GET /profile 响应：完整资料 + 活动参与记录。"""

    user: UserOut
    activities: List[ActivityParticipationOut] = []


class PublicUserOut(TZModel):
    """用户公开资料（无需登录，邮箱由 BFF 按需脱敏）。"""

    id: int
    email: EmailStr
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_type: str = "initial"
    github_url: Optional[str] = None
    website_url: Optional[str] = None
    tech_tags: List[str] = []
    created_at: datetime


class PublicUserProfileResponse(TZModel):
    """GET /users/{id} 响应：公开资料 + 论坛/考试统计。"""

    user: PublicUserOut
    stats: dict = {}
