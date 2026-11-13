"""学习闭环模型：错题本与复习状态。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime as _DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class WrongAnswer(Base):
    """用户与题目维度唯一的错题快照，不依赖题库后续是否被编辑。"""

    __tablename__ = "learning_wrong_answers"
    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="ux_learning_wrong_answers_user_question"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exam_id: Mapped[int] = mapped_column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id: Mapped[int] = mapped_column(Integer, ForeignKey("exam_questions.id", ondelete="CASCADE"), nullable=False, index=True)
    question_snapshot: Mapped[dict] = mapped_column(JSONDict, nullable=False)
    knowledge_tags: Mapped[Optional[list]] = mapped_column(JSONDict, nullable=True, default=list)
    latest_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correct_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mistake_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    review_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", index=True)
    review_due_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    last_wrong_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    last_reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)
