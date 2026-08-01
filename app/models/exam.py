"""考试模型：exams / exam_questions / exam_question_options / exam_attempts。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime as _DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class Exam(Base):
    """考试：status = draft | published | ended。"""

    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", index=True
    )
    start_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 技术方向标签（JSON 数组）
    tech_tags: Mapped[Optional[list]] = mapped_column(
        JSONDict, nullable=True, default=list
    )
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=now_utc,
        onupdate=now_utc,
    )

    def __repr__(self) -> str:
        return f"<Exam(id={self.id}, title='{self.title}', status='{self.status}')>"


class ExamQuestion(Base):
    """题目：type = single_choice | multiple_choice | programming。"""

    __tablename__ = "exam_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("exams.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="single_choice"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=5)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<ExamQuestion(id={self.id}, exam_id={self.exam_id}, type='{self.type}')>"
        )


class ExamQuestionOption(Base):
    """选项：is_correct 标记正确答案；label 为 A/B/C/D。"""

    __tablename__ = "exam_question_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("exam_questions.id"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return (
            f"<ExamQuestionOption(id={self.id}, question_id={self.question_id}, "
            f"label='{self.label}')>"
        )


class ExamAttempt(Base):
    """答题记录：(user_id, question_id) 唯一；is_correct/score 为 NULL 表示未批改。"""

    __tablename__ = "exam_attempts"

    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="ux_exam_attempts_unique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    exam_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("exams.id"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("exam_questions.id"), nullable=False, index=True
    )
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return (
            f"<ExamAttempt(id={self.id}, user_id={self.user_id}, "
            f"question_id={self.question_id})>"
        )
