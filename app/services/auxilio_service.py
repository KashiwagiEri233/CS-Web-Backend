"""Auxilio 学习助手服务：考试记录 → 薄弱标签 → 资源推荐。"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import ARRAY, String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc

from app.models.conversation import ChatMessage, Conversation
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

    async def create_conversation_with_user_msg(
        self, user_id: int, user_msg_content: str
    ) -> Conversation:
        """新会话：建会话(flush 取 id) + 落用户消息 + 同事务提交，返回会话。"""
        conv = Conversation(user_id=user_id, title="新会话")
        self.db.add(conv)
        await self.db.flush()
        self.db.add(
            ChatMessage(conversation_id=conv.id, role="user", content=user_msg_content)
        )
        await self.db.commit()
        return conv

    async def append_user_message(
        self, conversation_id: int, user_msg_content: str
    ) -> None:
        """既有会话：仅追加一条用户消息并提交。"""
        self.db.add(
            ChatMessage(
                conversation_id=conversation_id, role="user", content=user_msg_content
            )
        )
        await self.db.commit()

    async def persist_assistant_message(
        self, conv, assistant_text, tool_records, new_title
    ) -> None:
        """SSE 结束时落库助手消息 + 会话标题（失败不影响已输出内容）。

        注意：不能用 `async with self.db.begin()` 包裹——chat 流式期间查询会 autobegin
        只读事务，此时 begin() 抛 InvalidRequestError 被吞导致消息不落库；
        改为直接 add + commit（与 create_conversation_with_user_msg 一致）。
        """
        try:
            if new_title and conv.title == "新会话":
                conv.title = new_title
            if assistant_text:
                self.db.add(
                    ChatMessage(
                        conversation_id=conv.id,
                        role="assistant",
                        content="".join(assistant_text),
                        tool_calls=tool_records or None,
                    )
                )
            conv.updated_at = now_utc()
            await self.db.commit()
        except Exception:  # noqa: BLE001 - 持久化失败不影响已输出内容
            pass
