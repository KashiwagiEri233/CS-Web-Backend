"""Agent 每周复盘服务（AG-P3-04）。

复用 AG-P3-03 简报的素材管线，聚合到周窗口（配置时区周一为周起点）：
掌握度代理（新增错题）、专注时长、计划达成、任务完成、社区产出与下周建议。
每用户每周一份（唯一约束去重）；单节采集失败置 null + 整体 failed，
不影响工作台读取。数字均可追溯数据源；LLM 摘要后接（模型只负责解释）。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select

from app.core.timezone import local_day_start_utc, now_local
from app.models.agent_weekly_review import AgentWeeklyReview
from app.models.community import CommunityPost
from app.models.focus import FocusSession
from app.models.learning import WrongAnswer
from app.models.learning_plan import LearningPlanItem
from app.models.task import TaskClaim
from app.repositories.agent_weekly_review_repo import AgentWeeklyReviewRepository


def monday_of(d: date) -> date:
    """配置时区内取该日所在周的周一。"""
    return d - timedelta(days=d.weekday())


class AgentWeeklyReviewService:
    def __init__(self, db, audit=None):
        self.db = db
        self.repo = AgentWeeklyReviewRepository(db)
        self.audit = audit

    async def get_or_generate(
        self, user_id: int, week_start: Optional[date] = None
    ) -> AgentWeeklyReview:
        week = week_start or monday_of(now_local().date())
        existing = await self.repo.get_by_week(user_id, week)
        if existing is not None:
            return existing
        return await self._generate(user_id, week)

    async def _generate(self, user_id: int, week_start: date) -> AgentWeeklyReview:
        start = local_day_start_utc(week_start)
        end = local_day_start_utc(week_start + timedelta(days=7))
        content: dict = {}
        failed = False
        for key, collector in (
            ("focusMinutes", lambda: self._collect_focus(user_id, start, end)),
            ("newWrongAnswers", lambda: self._collect_wrong(user_id, start, end)),
            ("tasksApproved", lambda: self._collect_tasks(user_id, start, end)),
            ("communityPosts", lambda: self._collect_community(start, end)),
            ("planCompletion", lambda: self._collect_plan(user_id, week_start)),
            (
                "nextWeekHints",
                lambda: self._build_hints(user_id, week_start, start, end),
            ),
        ):
            try:
                content[key] = await collector()
            except Exception:  # noqa: BLE001 — 单节失败不阻断复盘
                content[key] = None
                failed = True
        status = "failed" if failed else "ready"
        return await self.repo.create(
            {
                "user_id": user_id,
                "week_start": week_start,
                "content": content,
                "status": status,
            }
        )

    async def _collect_focus(self, user_id: int, start, end) -> int:
        total = (
            await self.db.execute(
                select(func.coalesce(func.sum(FocusSession.duration_seconds), 0)).where(
                    FocusSession.user_id == user_id,
                    FocusSession.created_at >= start,
                    FocusSession.created_at < end,
                )
            )
        ).scalar_one()
        return int(total) // 60

    async def _collect_wrong(self, user_id: int, start, end) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(WrongAnswer)
                    .where(
                        WrongAnswer.user_id == user_id,
                        WrongAnswer.created_at >= start,
                        WrongAnswer.created_at < end,
                    )
                )
            ).scalar_one()
        )

    async def _collect_tasks(self, user_id: int, start, end) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(TaskClaim)
                    .where(
                        TaskClaim.user_id == user_id,
                        TaskClaim.status == "approved",
                        TaskClaim.completed_at >= start,
                        TaskClaim.completed_at < end,
                    )
                )
            ).scalar_one()
        )

    async def _collect_community(self, start, end) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(CommunityPost)
                    .where(
                        CommunityPost.status == "published",
                        CommunityPost.created_at >= start,
                        CommunityPost.created_at < end,
                    )
                )
            ).scalar_one()
        )

    async def _collect_plan(self, user_id: int, week_start: date) -> dict:
        """计划达成：本周学习计划项按状态计数（completed/total）。"""
        rows = (
            await self.db.execute(
                select(LearningPlanItem.status, func.count())
                .where(
                    LearningPlanItem.user_id == user_id,
                    LearningPlanItem.plan_date >= week_start,
                    LearningPlanItem.plan_date < week_start + timedelta(days=7),
                )
                .group_by(LearningPlanItem.status)
            )
        ).all()
        by_status = {status: int(n) for status, n in rows}
        total = sum(by_status.values())
        return {"completed": by_status.get("completed", 0), "total": total}

    async def _build_hints(
        self, user_id: int, week_start: date, start, end
    ) -> list[str]:
        """下周建议（规则派生，数字可追溯；LLM 解释后接）。"""
        hints: list[str] = []
        wrong = await self._collect_wrong(user_id, start, end)
        if wrong > 0:
            hints.append(f"本周新增 {wrong} 条错题，建议优先安排复习")
        focus_min = await self._collect_focus(user_id, start, end)
        if focus_min < 60:
            hints.append(f"本周专注仅 {focus_min} 分钟，可从每天一个番茄钟开始")
        plan = await self._collect_plan(
            user_id, week_start=start.date() if hasattr(start, "date") else start
        )
        if plan["total"] > 0 and plan["completed"] < plan["total"]:
            hints.append(
                f"本周计划完成 {plan['completed']}/{plan['total']}，未完成项可顺延或下调预算"
            )
        return hints
