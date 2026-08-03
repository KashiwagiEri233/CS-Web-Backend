"""Auxilio 学习助手服务：考试记录 → 薄弱标签 → 资源推荐。"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import ARRAY, String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exam import Exam, ExamAttempt, ExamQuestion
from app.models.resource import Resource

WEAKNESS_THRESHOLD = 0.6
MAX_RECOMMENDATIONS = 10


class AuxilioService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def analyze_learning_profile(self, user_id: int) -> dict:
        """分析用户答题历史：统计各技术标签正确率，识别薄弱点，推荐资源。"""
        rows = (
            await self.db.execute(
                select(ExamAttempt.is_correct, Exam.tech_tags)
                .join(ExamQuestion, ExamQuestion.id == ExamAttempt.question_id)
                .join(Exam, Exam.id == ExamAttempt.exam_id)
                .where(
                    ExamAttempt.user_id == user_id,
                    ExamAttempt.is_correct.is_not(None),
                )
            )
        ).all()

        if not rows:
            return {"weak_tags": [], "recommended_resources": []}

        tag_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0})
        for is_correct, exam_tags in rows:
            for tag in exam_tags or []:
                tag_stats[tag]["total"] += 1
                if is_correct:
                    tag_stats[tag]["correct"] += 1

        weak_tags = []
        for tag, stats in tag_stats.items():
            accuracy = stats["correct"] / stats["total"] if stats["total"] else 0
            if accuracy < WEAKNESS_THRESHOLD:
                weak_tags.append(
                    {
                        "tag": tag,
                        "total": stats["total"],
                        "correct": stats["correct"],
                        "accuracy": round(accuracy, 4),
                    }
                )
        weak_tags.sort(key=lambda t: t["accuracy"])

        recommended = []
        if weak_tags:
            weak_tag_names = [t["tag"] for t in weak_tags]
            resources = (
                (
                    await self.db.execute(
                        select(Resource)
                        .where(
                            Resource.status == "approved",
                            Resource.tech_tags.op("?|")(
                                cast(weak_tag_names, ARRAY(String))
                            ),
                        )
                        .order_by(
                            Resource.view_count.desc(), Resource.like_count.desc()
                        )
                        .limit(MAX_RECOMMENDATIONS)
                    )
                )
                .scalars()
                .all()
            )
            recommended = [
                {
                    "id": r.id,
                    "title": r.title,
                    "url": r.url,
                    "description": r.description,
                    "resource_type": r.resource_type,
                    "tech_tags": r.tech_tags or [],
                }
                for r in resources
            ]

        return {"weak_tags": weak_tags, "recommended_resources": recommended}
