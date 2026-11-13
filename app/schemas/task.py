"""任务与团队 API schema（P3）。

- 金额跨 JSON 边界使用正整数字符串（reward_total）。
- 入参 extra=forbid；PATCH 使用 exclude_unset 由服务层处理。
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.schemas.base import TZModel

_DECIMAL_MONEY = r"^[1-9][0-9]*$"


class TaskCreate(BaseModel):
    title: str = Field(min_length=5, max_length=50)
    description: str = Field(min_length=10, max_length=500)
    content_markdown: Optional[str] = Field(default=None, max_length=20000)
    difficulty: Optional[str] = Field(default=None, max_length=20)
    category: str = Field(default="general", max_length=50)
    tags: List[str] = Field(default_factory=list, max_length=10)
    execution_mode: Literal["single", "team"] = "single"
    reward_total: str = Field(pattern=_DECIMAL_MONEY, max_length=19)
    max_members: int = Field(default=1, ge=1, le=100)
    deadline: datetime
    visibility: Literal["public", "members", "peak"] = "members"
    peak_id: Optional[int] = Field(default=None, gt=0)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def _check_members_and_visibility(self) -> "TaskCreate":
        if self.execution_mode == "single" and self.max_members != 1:
            raise ValueError("单人任务人数必须为 1")
        if self.execution_mode == "team" and self.max_members < 2:
            raise ValueError("团队任务人数至少为 2")
        if self.visibility == "peak" and not self.peak_id:
            raise ValueError("峰内可见任务必须指定 peak_id")
        return self


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=5, max_length=50)
    description: Optional[str] = Field(default=None, min_length=10, max_length=500)
    content_markdown: Optional[str] = Field(default=None, max_length=20000)
    difficulty: Optional[str] = Field(default=None, max_length=20)
    category: Optional[str] = Field(default=None, max_length=50)
    tags: Optional[List[str]] = Field(default=None, max_length=10)
    execution_mode: Optional[Literal["single", "team"]] = None
    reward_total: Optional[str] = Field(default=None, pattern=_DECIMAL_MONEY, max_length=19)
    max_members: Optional[int] = Field(default=None, ge=1, le=100)
    deadline: Optional[datetime] = None
    visibility: Optional[Literal["public", "members", "peak"]] = None
    peak_id: Optional[int] = Field(default=None, gt=0)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ActiveClaimMemberOut(TZModel):
    user_id: int
    display_name: Optional[str] = None
    is_leader: bool = False


class ActiveClaimOut(TZModel):
    """任务详情附带的当前执行实例摘要（不递归包含任务）。"""

    id: int
    status: str
    leader_user_id: int
    members: List[ActiveClaimMemberOut] = Field(default_factory=list)


class TaskOut(TZModel):
    id: int
    title: str
    description: str
    content_markdown: Optional[str] = None
    difficulty: Optional[str] = None
    category: str
    tags: List[str] = Field(default_factory=list)
    execution_mode: str
    reward_total: int
    max_members: int
    status: str
    publisher_id: int
    publisher_name: Optional[str] = None
    visibility: str
    peak_id: Optional[int] = None
    deadline: Optional[datetime] = None
    version: int = 1
    review_cycle: int = 0
    reviewed_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    active_claim: Optional[ActiveClaimOut] = None

    @field_serializer("reward_total")
    def _money_str(self, value: int) -> str:
        return str(value)


class TaskActionOut(TZModel):
    id: int
    task_id: int
    claim_id: Optional[int] = None
    actor_id: int
    action: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    reason: Optional[str] = None
    created_at: Optional[datetime] = None


class ClaimMemberOut(TZModel):
    user_id: int
    display_name: Optional[str] = None
    is_leader: bool = False


class SubmissionOut(TZModel):
    id: int
    claim_id: int
    revision: int
    description: Optional[str] = None
    attachments: List[str] = Field(default_factory=list)
    submitted_by: int
    review_status: str
    reviewer_id: Optional[int] = None
    review_note: Optional[str] = None
    created_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None


class TaskClaimOut(TZModel):
    id: int
    task_id: int
    team_id: Optional[int] = None
    leader_user_id: int
    status: str
    started_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    version: int = 1
    members: List[ClaimMemberOut] = Field(default_factory=list)
    submission: Optional[SubmissionOut] = None
    task: Optional[TaskOut] = None


class ClaimCreate(BaseModel):
    """单人任务无业务体；团队任务必须提供 team_id。"""

    team_id: Optional[int] = Field(default=None, gt=0)

    model_config = ConfigDict(extra="forbid")


class SubmissionCreate(BaseModel):
    description: str = Field(min_length=10, max_length=5000)
    attachments: List[str] = Field(default_factory=list, max_length=10)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TaskReviewCreate(BaseModel):
    decision: Literal["approve", "reject"]
    note: Optional[str] = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def _reject_note(self) -> "TaskReviewCreate":
        if self.decision == "reject" and not self.note:
            raise ValueError("驳回必须填写原因")
        return self


class SubmissionReviewCreate(BaseModel):
    decision: Literal["approve", "reject"]
    note: Optional[str] = Field(default=None, max_length=500)
    rework_deadline: Optional[datetime] = None

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def _reject_requires_deadline(self) -> "SubmissionReviewCreate":
        if self.decision == "reject":
            if not self.note:
                raise ValueError("驳回必须填写原因")
            if not self.rework_deadline:
                raise ValueError("驳回必须给出新的返工截止时间")
        return self


class ForceCloseCreate(BaseModel):
    reason: str = Field(min_length=5, max_length=500)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    invitee_user_ids: List[int] = Field(default_factory=list, max_length=20)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TeamUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TeamMemberOut(TZModel):
    user_id: int
    display_name: Optional[str] = None
    role: str
    status: str
    joined_at: Optional[datetime] = None


class TeamOut(TZModel):
    id: int
    name: str
    captain_user_id: int
    status: str
    version: int = 1
    members: List[TeamMemberOut] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class InvitationCreate(BaseModel):
    invitee_user_id: int = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


class InvitationOut(TZModel):
    id: int
    team_id: int
    invitee_user_id: int
    inviter_user_id: int
    status: str
    expires_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class ClaimCancelOut(TZModel):
    claim_id: int
    task_status: str
    settlement: Optional[str] = None
