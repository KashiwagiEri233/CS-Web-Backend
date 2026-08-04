"""工具集模块 schema：考试 / 资源 / 任务 / 积分 / Auxilio / 组件注册表。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.base import TZModel

# ------------------------------------------------------------------ 考试

EXAM_LIMITS = {
    "TITLE_MAX": 100,
    "DESC_MAX": 1000,
    "TAGS_MAX": 10,
    "TAG_MAX": 30,
}


class ExamInput(BaseModel):
    title: str
    description: Optional[str] = None
    status: str = "draft"
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    tech_tags: Optional[List[str]] = None
    questions: Optional[List["QuestionInput"]] = None
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        if len(v) > EXAM_LIMITS["TITLE_MAX"]:
            raise ValueError(f"标题不能超过 {EXAM_LIMITS['TITLE_MAX']} 字符")
        return v

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        if v not in {"draft", "published", "ended"}:
            raise ValueError("状态必须为 draft / published / ended")
        return v


class QuestionInput(BaseModel):
    type: str = "single_choice"
    title: str
    content_markdown: Optional[str] = None
    score: int = 5
    sort_order: int = 0
    options: Optional[List[Dict[str, Any]]] = None  # [{label, content, is_correct}]
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in {"single_choice", "multiple_choice", "programming"}:
            raise ValueError("题目类型无效")
        return v


class ExamAttemptInput(BaseModel):
    question_id: int
    answer: str


class ExamSubmitIn(BaseModel):
    answers: List[ExamAttemptInput]


class ExamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: Optional[str] = None
    status: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    tech_tags: Optional[List[str]] = None
    created_by: int
    created_at: datetime
    updated_at: datetime


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    exam_id: int
    type: str
    title: str
    content_markdown: Optional[str] = None
    score: int
    sort_order: int
    options: List[Dict[str, Any]] = []
    created_at: datetime


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    exam_id: int
    question_id: int
    answer: Optional[str] = None
    is_correct: Optional[bool] = None
    score: Optional[int] = None
    submitted_at: datetime


class RankingEntry(BaseModel):
    user_id: int
    display_name: Optional[str] = None
    total_score: int
    total_questions: int
    correct_count: int
    submitted_at: Optional[datetime] = None


# ------------------------------------------------------------------ 资源

RESOURCE_TYPES = {"article", "video", "course", "book", "tool", "other"}


class ResourceInput(BaseModel):
    title: str
    url: str
    description: Optional[str] = None
    resource_type: str = "article"
    tech_tags: Optional[List[str]] = None
    file_url: Optional[str] = None
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        return v

    @field_validator("resource_type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in RESOURCE_TYPES:
            raise ValueError("资源类型无效")
        return v


class ResourceOut(TZModel):
    id: int
    title: str
    url: str
    description: Optional[str] = None
    resource_type: str
    tech_tags: List[str] = []
    status: str
    submitted_by: int
    submitted_by_name: Optional[str] = None
    reviewed_by: Optional[int] = None
    review_note: Optional[str] = None
    file_url: Optional[str] = None
    view_count: int
    like_count: int
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------ 任务


class TaskInput(BaseModel):
    title: str
    description: str
    content_markdown: Optional[str] = None
    category: str = "general"
    tags: Optional[List[str]] = None
    points: int = 10
    max_claimants: int = 1
    status: str = "draft"
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        return v

    @field_validator("description")
    @classmethod
    def _validate_description(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("描述不能为空")
        return v

    @field_validator("points")
    @classmethod
    def _validate_points(cls, v: int) -> int:
        if v < 0:
            raise ValueError("积分不能为负数")
        return v

    @field_validator("max_claimants")
    @classmethod
    def _validate_max_claimants(cls, v: int) -> int:
        if v < 1:
            raise ValueError("认领人数至少为 1")
        return v


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    content_markdown: Optional[str] = None
    category: str
    tags: Optional[List[str]] = None
    points: int
    max_claimants: int
    status: str
    created_by: int
    published_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class TaskClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    user_id: int
    display_name: Optional[str] = None
    status: str
    claim_note: Optional[str] = None
    completed_at: Optional[datetime] = None
    reviewed_by: Optional[int] = None
    review_note: Optional[str] = None
    created_at: datetime


# ------------------------------------------------------------------ 积分


class PointsTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    amount: int
    reason: str
    source_type: str
    source_id: Optional[int] = None
    balance_after: int
    created_at: datetime


class PointsProfileOut(BaseModel):
    balance: int
    level: int
    level_title: str
    transactions: List[PointsTransactionOut] = []


class LeaderboardEntry(BaseModel):
    user_id: int
    display_name: Optional[str] = None
    balance: int
    level: int
    level_title: str


# ------------------------------------------------------------------ Auxilio


class WeaknessTag(BaseModel):
    tag: str
    total: int
    correct: int
    accuracy: float


class RecommendedResource(BaseModel):
    id: int
    title: str
    url: str
    description: Optional[str] = None
    resource_type: str
    tech_tags: List[str] = []


class AuxilioAnalysis(BaseModel):
    weak_tags: List[WeaknessTag] = []
    recommended_resources: List[RecommendedResource] = []


# ------------------------------------------------------------------ 组件注册表


class ComponentItemInput(BaseModel):
    name: str
    slug: str
    category: str = "general"
    description: Optional[str] = None
    sort_order: int = 0
    migration_status: str = "legacy"
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("name", "slug")
    @classmethod
    def _validate_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("名称/slug 不能为空")
        return v


class ComponentVariantInput(BaseModel):
    size: str
    color: str
    state: str
    is_enabled: bool = True


class ComponentGuideInput(BaseModel):
    use_cases: List[str] = []
    anti_patterns: List[str] = []


class ComponentItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    category: str
    description: Optional[str] = None
    migration_status: str
    sort_order: int
    variants: List[Dict[str, Any]] = []
    guide: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
