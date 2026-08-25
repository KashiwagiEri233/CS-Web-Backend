"""Auxilio 学习助手服务：考试记录 → 薄弱标签 → 资源推荐。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import ARRAY, String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.core.loguru_logger import get_logger

from app.models.conversation import AgentRun, ChatMessage, Conversation
from app.models.exam import Exam, ExamAttempt, ExamQuestion
from app.models.learning import WrongAnswer
from app.models.learning_goal import LearningGoal
from app.models.learning_plan import LearningPlanItem
from app.models.focus import FocusSession
from app.models.resource import Resource

WEAKNESS_THRESHOLD = 0.6
MAX_RECOMMENDATIONS = 10
MAX_WEEKLY_BUDGET_MINUTES = 10080
MASTERY_PRIOR_STRENGTH = 2.0
MASTERY_HALF_LIFE_DAYS = 30.0
REVIEW_FEEDBACK = {"again", "hard", "good", "easy"}
GOOD_INTERVAL_DAYS = (1, 3, 7, 14, 30, 60)
EASY_INTERVAL_DAYS = (4, 10, 21, 45, 90, 120)
logger = get_logger("auxilio.service")


class AuxilioService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def analyze_learning_profile(self, user_id: int) -> dict:
        """分析用户答题历史：正确率、时间衰减、置信度和错题证据。"""
        rows = (
            await self.db.execute(
                select(
                    ExamAttempt.question_id,
                    ExamAttempt.is_correct,
                    ExamAttempt.submitted_at,
                    Exam.tech_tags,
                )
                .join(ExamQuestion, ExamQuestion.id == ExamAttempt.question_id)
                .join(Exam, Exam.id == ExamAttempt.exam_id)
                .where(
                    ExamAttempt.user_id == user_id,
                    ExamAttempt.is_correct.is_not(None),
                )
            )
        ).all()

        if not rows:
            return {
                "knowledge_points": [],
                "weak_tags": [],
                "recommended_resources": [],
            }

        wrong_counts = {
            question_id: mistake_count
            for question_id, mistake_count in (
                await self.db.execute(
                    select(WrongAnswer.question_id, WrongAnswer.mistake_count).where(
                        WrongAnswer.user_id == user_id
                    )
                )
            ).all()
        }
        now = now_utc()
        tag_stats: dict[str, dict] = defaultdict(
            lambda: {
                "total": 0,
                "correct": 0,
                "incorrect": 0,
                "weighted_total": 0.0,
                "weighted_correct": 0.0,
                "mistake_count": 0,
                "last_attempt_at": None,
            }
        )
        for question_id, is_correct, submitted_at, exam_tags in rows:
            age_days = 0.0
            if submitted_at is not None:
                age_days = max(0.0, (now - submitted_at).total_seconds() / 86400)
            recency_weight = 0.5 ** (age_days / MASTERY_HALF_LIFE_DAYS)
            for tag in exam_tags or []:
                tag_stats[tag]["total"] += 1
                if is_correct:
                    tag_stats[tag]["correct"] += 1
                    tag_stats[tag]["weighted_correct"] += recency_weight
                else:
                    tag_stats[tag]["incorrect"] += 1
                tag_stats[tag]["weighted_total"] += recency_weight
                tag_stats[tag]["mistake_count"] += wrong_counts.get(question_id, 0)
                last_attempt_at = tag_stats[tag]["last_attempt_at"]
                if last_attempt_at is None or (
                    submitted_at is not None and submitted_at > last_attempt_at
                ):
                    tag_stats[tag]["last_attempt_at"] = submitted_at

        knowledge_points = []
        weak_tags = []
        for tag, stats in tag_stats.items():
            accuracy = stats["correct"] / stats["total"] if stats["total"] else 0
            smoothed_accuracy = (stats["correct"] + MASTERY_PRIOR_STRENGTH * 0.5) / (
                stats["total"] + MASTERY_PRIOR_STRENGTH
            )
            recency_accuracy = (
                stats["weighted_correct"] / stats["weighted_total"]
                if stats["weighted_total"]
                else 0.0
            )
            decay_factor = min(
                1.0,
                stats["weighted_total"] / stats["total"] if stats["total"] else 0.0,
            )
            mastery_score = (smoothed_accuracy * 0.6 + recency_accuracy * 0.4) * (
                0.6 + 0.4 * decay_factor
            )
            confidence = min(1.0, stats["weighted_total"] / 5.0)
            # 低样本结果仍可进入薄弱点队列，但通过 confidence 明确标记为待验证。
            profile = {
                "tag": tag,
                "total": stats["total"],
                "correct": stats["correct"],
                "accuracy": round(accuracy, 4),
                "incorrect": stats["incorrect"],
                "mistake_count": stats["mistake_count"],
                "mastery_score": round(mastery_score, 4),
                "confidence": round(confidence, 4),
                "confidence_label": (
                    "high"
                    if confidence >= 0.8
                    else "medium" if confidence >= 0.4 else "low"
                ),
                "recency_accuracy": round(recency_accuracy, 4),
                "decay_factor": round(decay_factor, 4),
                "last_attempt_at": (
                    stats["last_attempt_at"].isoformat()
                    if stats["last_attempt_at"]
                    else None
                ),
            }
            knowledge_points.append(profile)
            if mastery_score < WEAKNESS_THRESHOLD:
                weak_tags.append(profile)
        knowledge_points.sort(key=lambda t: (t["mastery_score"], -t["confidence"]))
        weak_tags.sort(key=lambda t: (t["mastery_score"], -t["confidence"]))

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

        return {
            "knowledge_points": knowledge_points,
            "weak_tags": weak_tags,
            "recommended_resources": recommended,
        }

    async def review_wrong_answer(
        self,
        user_id: int,
        mistake_id: int,
        feedback: str,
        error_reason: str | None = None,
    ) -> WrongAnswer:
        """按用户反馈推进错题复习状态，并计算下一次到期时间。"""
        if feedback not in REVIEW_FEEDBACK:
            raise ValueError("复习反馈必须是 again、hard、good 或 easy")
        row = (
            await self.db.execute(
                select(WrongAnswer).where(
                    WrongAnswer.id == mistake_id,
                    WrongAnswer.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise LookupError("错题不存在")
        now = now_utc()
        row.last_reviewed_at = now
        if error_reason is not None:
            row.error_reason = error_reason.strip() or row.error_reason
        if feedback == "again":
            row.review_streak = 0
            row.status = "new"
            row.review_due_at = now + timedelta(minutes=10)
        elif feedback == "hard":
            row.review_streak = max(1, row.review_streak)
            row.status = "reviewing"
            row.review_due_at = now + timedelta(days=1)
        else:
            row.review_streak = min(row.review_streak + 1, len(GOOD_INTERVAL_DAYS))
            row.status = "mastered" if feedback == "easy" else "reviewing"
            intervals = EASY_INTERVAL_DAYS if feedback == "easy" else GOOD_INTERVAL_DAYS
            row.review_due_at = now + timedelta(days=intervals[row.review_streak - 1])
        await self.db.commit()
        return row

    async def list_learning_goals(
        self, user_id: int, include_completed: bool = False
    ) -> list[LearningGoal]:
        query = select(LearningGoal).where(LearningGoal.user_id == user_id)
        if not include_completed:
            query = query.where(LearningGoal.status != "completed")
        result = await self.db.execute(
            query.order_by(
                LearningGoal.target_date.asc().nullslast(), LearningGoal.id.asc()
            )
        )
        return list(result.scalars().all())

    async def create_learning_goal(
        self,
        user_id: int,
        *,
        title: str,
        exam_id: int | None,
        description: str | None,
        target_date,
        weekly_budget_minutes: int,
        preferred_slots: list[str] | None,
    ) -> LearningGoal:
        normalized_title = " ".join(title.split()).strip()
        if not normalized_title:
            raise ValueError("学习目标标题不能为空")
        if (
            weekly_budget_minutes < 15
            or weekly_budget_minutes > MAX_WEEKLY_BUDGET_MINUTES
        ):
            raise ValueError("每周时间预算必须在 15 到 10080 分钟之间")
        if exam_id is not None and await self.db.get(Exam, exam_id) is None:
            raise ValueError("关联考试不存在")
        if target_date is not None:
            if target_date.tzinfo is None:
                target_date = target_date.replace(tzinfo=timezone.utc)
            if target_date <= now_utc():
                raise ValueError("目标截止时间必须晚于当前时间")
        slots = [
            " ".join(slot.split()) for slot in (preferred_slots or []) if slot.strip()
        ]
        if len(slots) > 14:
            raise ValueError("偏好时段最多 14 个")
        goal = LearningGoal(
            user_id=user_id,
            exam_id=exam_id,
            title=normalized_title[:200],
            description=description.strip()[:2000] if description else None,
            target_date=target_date,
            weekly_budget_minutes=weekly_budget_minutes,
            preferred_slots=slots,
            status="active",
        )
        self.db.add(goal)
        await self.db.commit()
        return goal

    async def update_learning_goal(
        self, user_id: int, goal_id: int, **changes
    ) -> LearningGoal:
        goal = (
            await self.db.execute(
                select(LearningGoal).where(
                    LearningGoal.id == goal_id,
                    LearningGoal.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if goal is None:
            raise LookupError("学习目标不存在")
        if "title" in changes and changes["title"] is not None:
            title = " ".join(changes["title"].split()).strip()
            if not title:
                raise ValueError("学习目标标题不能为空")
            goal.title = title[:200]
        if (
            "weekly_budget_minutes" in changes
            and changes["weekly_budget_minutes"] is not None
        ):
            budget = changes["weekly_budget_minutes"]
            if budget < 15 or budget > MAX_WEEKLY_BUDGET_MINUTES:
                raise ValueError("每周时间预算必须在 15 到 10080 分钟之间")
            goal.weekly_budget_minutes = budget
        if "exam_id" in changes:
            exam_id = changes["exam_id"]
            if exam_id is not None and await self.db.get(Exam, exam_id) is None:
                raise ValueError("关联考试不存在")
            goal.exam_id = exam_id
        if "target_date" in changes:
            target_date = changes["target_date"]
            if target_date is not None:
                if target_date.tzinfo is None:
                    target_date = target_date.replace(tzinfo=timezone.utc)
                if target_date <= now_utc():
                    raise ValueError("目标截止时间必须晚于当前时间")
            goal.target_date = target_date
        if "description" in changes:
            goal.description = (
                changes["description"].strip()[:2000]
                if changes["description"]
                else None
            )
        if "preferred_slots" in changes and changes["preferred_slots"] is not None:
            slots = [
                " ".join(slot.split())
                for slot in changes["preferred_slots"]
                if slot.strip()
            ]
            if len(slots) > 14:
                raise ValueError("偏好时段最多 14 个")
            goal.preferred_slots = slots
        if "status" in changes and changes["status"] is not None:
            if changes["status"] not in {"active", "paused", "completed"}:
                raise ValueError("目标状态无效")
            goal.status = changes["status"]
        goal.updated_at = now_utc()
        await self.db.commit()
        return goal

    async def delete_learning_goal(self, user_id: int, goal_id: int) -> None:
        goal = (
            await self.db.execute(
                select(LearningGoal).where(
                    LearningGoal.id == goal_id,
                    LearningGoal.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if goal is None:
            raise LookupError("学习目标不存在")
        await self.db.delete(goal)
        await self.db.commit()

    async def list_learning_plan(
        self, user_id: int, plan_date: date, *, generate: bool = False
    ) -> list[LearningPlanItem]:
        if generate:
            await self.generate_learning_plan(user_id, plan_date)
        result = await self.db.execute(
            select(LearningPlanItem)
            .where(
                LearningPlanItem.user_id == user_id,
                LearningPlanItem.plan_date == plan_date,
            )
            .order_by(LearningPlanItem.status.asc(), LearningPlanItem.id.asc())
        )
        return list(result.scalars().all())

    async def generate_learning_plan(
        self, user_id: int, plan_date: date
    ) -> list[LearningPlanItem]:
        """按用户预算生成幂等的日计划；已有计划项不被自动覆盖。"""
        existing = await self.list_learning_plan(user_id, plan_date)
        if existing:
            return existing
        goals = await self.list_learning_goals(user_id)
        if not goals:
            return []
        # 不用最小值抬高预算：每周 15 分钟的目标不能被错误地扩成每天 15 分钟。
        daily_budget = sum(goal.weekly_budget_minutes for goal in goals) // 7
        focus_start = datetime.combine(
            plan_date, datetime.min.time(), tzinfo=timezone.utc
        )
        focus_end = focus_start + timedelta(days=1)
        focused = int(
            (
                await self.db.execute(
                    select(
                        func.coalesce(func.sum(FocusSession.duration_seconds), 0)
                    ).where(
                        FocusSession.user_id == user_id,
                        FocusSession.phase == "focus",
                        FocusSession.created_at >= focus_start,
                        FocusSession.created_at < focus_end,
                    )
                )
            ).scalar_one()
            // 60
        )
        remaining = max(0, daily_budget - focused)
        if remaining < 15:
            return []
        primary_goal = goals[0]
        items: list[dict] = []
        due_rows = list(
            (
                await self.db.execute(
                    select(WrongAnswer)
                    .where(
                        WrongAnswer.user_id == user_id,
                        WrongAnswer.status != "mastered",
                        WrongAnswer.review_due_at <= now_utc(),
                    )
                    .order_by(WrongAnswer.review_due_at.asc(), WrongAnswer.id.asc())
                    .limit(8)
                )
            )
            .scalars()
            .all()
        )
        for row in due_rows:
            items.append(
                {
                    "goal_id": row.exam_id
                    and next(
                        (g.id for g in goals if g.exam_id == row.exam_id),
                        primary_goal.id,
                    ),
                    "source_type": "mistake",
                    "source_key": str(row.id),
                    "title": (
                        f"复习错题：{(row.question_snapshot or {}).get('title') or '未命名题目'}"
                    ),
                    "rationale": f"到期错题，已错 {row.mistake_count} 次；优先复习可减少遗忘。",
                    "estimated_minutes": 15,
                    "metadata_json": {
                        "mistakeId": row.id,
                        "tags": row.knowledge_tags or [],
                    },
                }
            )
        profile = await self.analyze_learning_profile(user_id)
        for point in (profile.get("weak_tags") or [])[:4]:
            items.append(
                {
                    "goal_id": primary_goal.id,
                    "source_type": "knowledge",
                    "source_key": str(point["tag"]),
                    "title": f"巩固知识点：{point['tag']}",
                    "rationale": (
                        f"掌握度 {point['mastery_score']:.0%}，置信度 "
                        f"{point['confidence_label']}；建议短时练习。"
                    ),
                    "estimated_minutes": 25,
                    "metadata_json": {
                        "tag": point["tag"],
                        "masteryScore": point["mastery_score"],
                    },
                }
            )
        for resource in (profile.get("recommended_resources") or [])[:4]:
            items.append(
                {
                    "goal_id": primary_goal.id,
                    "source_type": "resource",
                    "source_key": str(resource["id"]),
                    "title": f"学习资源：{resource['title']}",
                    "rationale": "资源标签与当前薄弱知识点匹配。",
                    "estimated_minutes": 30,
                    "metadata_json": {
                        "resourceId": resource["id"],
                        "url": resource.get("url"),
                    },
                }
            )
        consumed = 0
        for payload in items:
            if consumed + payload["estimated_minutes"] > remaining:
                continue
            self.db.add(
                LearningPlanItem(
                    user_id=user_id,
                    plan_date=plan_date,
                    **payload,
                )
            )
            consumed += payload["estimated_minutes"]
        await self.db.commit()
        return await self.list_learning_plan(user_id, plan_date)

    async def update_learning_plan_item(
        self,
        user_id: int,
        item_id: int,
        *,
        status: str | None = None,
        locked: bool | None = None,
        defer_to: date | None = None,
    ) -> LearningPlanItem:
        item = (
            await self.db.execute(
                select(LearningPlanItem).where(
                    LearningPlanItem.id == item_id,
                    LearningPlanItem.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if item is None:
            raise LookupError("计划项不存在")
        if item.locked and defer_to is not None:
            raise ValueError("锁定计划项不可延期")
        if status is not None:
            if status not in {"planned", "completed", "deferred", "skipped"}:
                raise ValueError("计划项状态无效")
            item.status = status
            item.completed_at = now_utc() if status == "completed" else None
        if locked is not None:
            item.locked = locked
        if defer_to is not None:
            if defer_to <= item.plan_date:
                raise ValueError("延期日期必须晚于当前计划日期")
            conflict = (
                await self.db.execute(
                    select(LearningPlanItem).where(
                        LearningPlanItem.user_id == user_id,
                        LearningPlanItem.plan_date == defer_to,
                        LearningPlanItem.source_type == item.source_type,
                        LearningPlanItem.source_key == item.source_key,
                        LearningPlanItem.id != item.id,
                    )
                )
            ).scalar_one_or_none()
            if conflict is not None:
                raise ValueError("目标日期已存在相同计划项")
            item.plan_date = defer_to
            item.status = "planned"
        item.updated_at = now_utc()
        await self.db.commit()
        return item

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

    async def create_agent_run(
        self,
        *,
        user_id: int,
        conversation_id: int | None,
        input_message_id: int | None,
        preset_id: str | None,
        trigger_type: str = "chat",
    ) -> AgentRun:
        """创建一次执行记录，并在开始流式处理前提交其身份。"""
        run = AgentRun(
            user_id=user_id,
            conversation_id=conversation_id,
            input_message_id=input_message_id,
            preset_id=preset_id,
            trigger_type=trigger_type,
            status="running",
            started_at=now_utc(),
        )
        self.db.add(run)
        await self.db.commit()
        return run

    async def finish_agent_run(
        self,
        run: AgentRun,
        *,
        status: str,
        output_message_id: int | None = None,
        usage: dict | None = None,
        error_message: str | None = None,
        started_at=None,
    ) -> None:
        """以终态收敛 run；失败不应掩盖已经发送给用户的流。"""
        try:
            run.status = status
            run.output_message_id = output_message_id
            run.completed_at = now_utc()
            run.error_message = error_message
            if usage:
                run.prompt_tokens = int(usage.get("prompt_tokens") or 0)
                run.completion_tokens = int(usage.get("completion_tokens") or 0)
                run.total_tokens = int(usage.get("total_tokens") or 0)
            if started_at is not None:
                run.latency_ms = int((now_utc() - started_at).total_seconds() * 1000)
            await self.db.commit()
        except Exception as exc:  # noqa: BLE001 - 运行态记录是 best-effort
            await self.db.rollback()
            logger.warning(
                "Agent run finalization failed",
                run_id=run.id,
                error_type=type(exc).__name__,
            )

    async def fork_conversation(
        self,
        source: Conversation,
        *,
        from_message_id: int | None = None,
        title: str | None = None,
    ) -> tuple[Conversation, int]:
        """复制源会话截至某条消息的快照，创建独立分支。"""
        # 锁定会话元数据，避免分支事务与标题/更新时间并发写入产生半快照。
        source = (
            await self.db.execute(
                select(Conversation)
                .where(Conversation.id == source.id)
                .with_for_update()
            )
        ).scalar_one()
        query = select(ChatMessage).where(ChatMessage.conversation_id == source.id)
        if from_message_id is not None:
            query = query.where(ChatMessage.id <= from_message_id)
        messages = list(
            (await self.db.execute(query.order_by(ChatMessage.id.asc())))
            .scalars()
            .all()
        )
        if from_message_id is not None and not any(
            m.id == from_message_id for m in messages
        ):
            raise ValueError("分支消息不属于源会话")
        root_id = source.root_conversation_id or source.id
        branch = Conversation(
            user_id=source.user_id,
            title=(title or f"{source.title}（分支）")[:200],
            parent_conversation_id=source.id,
            root_conversation_id=root_id,
            forked_from_message_id=from_message_id,
        )
        self.db.add(branch)
        await self.db.flush()
        for message in messages:
            self.db.add(
                ChatMessage(
                    conversation_id=branch.id,
                    role=message.role,
                    content=message.content,
                    tool_calls=message.tool_calls,
                    created_at=message.created_at,
                )
            )
        await self.db.commit()
        return branch, len(messages)

    async def rename_conversation(
        self, conversation: Conversation, title: str
    ) -> Conversation:
        """更新会话标题；标题为空或仅空白时拒绝。"""
        normalized = " ".join(title.split()).strip()
        if not normalized:
            raise ValueError("会话标题不能为空")
        conversation.title = normalized[:200]
        conversation.updated_at = now_utc()
        await self.db.commit()
        return conversation

    async def set_conversation_archived(
        self, conversation: Conversation, archived: bool
    ) -> Conversation:
        """归档/取消归档会话。归档不会改变消息或分支关系。"""
        conversation.archived_at = now_utc() if archived else None
        conversation.updated_at = now_utc()
        await self.db.commit()
        return conversation

    async def delete_conversation(
        self, conversation: Conversation, *, cascade: bool = False
    ) -> int:
        """软删除会话。

        默认要求不存在活跃子分支；cascade=True 时递归软删除整棵子树。保留关系
        和消息数据，避免悬空引用并为未来恢复/审计保留依据。
        """
        rows = list(
            (
                await self.db.execute(
                    select(Conversation)
                    .where(Conversation.user_id == conversation.user_id)
                    .order_by(Conversation.id.asc())
                )
            )
            .scalars()
            .all()
        )
        by_parent: dict[int | None, list[Conversation]] = defaultdict(list)
        for row in rows:
            by_parent[row.parent_conversation_id].append(row)
        descendants: list[Conversation] = []
        queue = list(by_parent.get(conversation.id, []))
        while queue:
            child = queue.pop(0)
            descendants.append(child)
            queue.extend(by_parent.get(child.id, []))
        active_children = [child for child in descendants if child.deleted_at is None]
        if active_children and not cascade:
            raise ValueError("会话仍有活跃子分支；请先处理子分支或确认级联删除")
        targets = [conversation, *descendants] if cascade else [conversation]
        timestamp = now_utc()
        for target in targets:
            if target.deleted_at is None:
                target.deleted_at = timestamp
                target.archived_at = timestamp
                target.updated_at = timestamp
        await self.db.commit()
        return sum(1 for target in targets if target.deleted_at == timestamp)

    async def append_user_message(
        self, conversation_id: int, user_msg_content: str
    ) -> int | None:
        """既有会话：仅追加一条用户消息并提交。"""
        message = ChatMessage(
            conversation_id=conversation_id, role="user", content=user_msg_content
        )
        self.db.add(message)
        await self.db.flush()
        await self.db.commit()
        return message.id

    async def persist_assistant_message(
        self, conv, assistant_text, tool_records, new_title
    ) -> int | None:
        """SSE 结束时落库助手消息 + 会话标题（失败不影响已输出内容）。

        注意：不能用 `async with self.db.begin()` 包裹——chat 流式期间查询会 autobegin
        只读事务，此时 begin() 抛 InvalidRequestError 被吞导致消息不落库；
        改为直接 add + commit（与 create_conversation_with_user_msg 一致）。
        """
        try:
            if new_title and conv.title == "新会话":
                conv.title = new_title
            output_message_id = None
            if assistant_text:
                message = ChatMessage(
                    conversation_id=conv.id,
                    role="assistant",
                    content="".join(assistant_text),
                    tool_calls=tool_records or None,
                )
                self.db.add(message)
                await self.db.flush()
                output_message_id = message.id
            conv.updated_at = now_utc()
            await self.db.commit()
            return output_message_id
        except Exception as exc:  # noqa: BLE001 - 持久化失败不影响已输出内容
            await self.db.rollback()
            logger.warning(
                "Assistant message persistence failed",
                conversation_id=getattr(conv, "id", None),
                error_type=type(exc).__name__,
            )
        return None
