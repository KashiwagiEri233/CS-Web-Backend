"""Agent 每日学习简报服务（AG-P3-03）。

管线对齐 Aervox diary 域（RootDoc-AgentEval.md §2）：素材窗口采集 →
生成 → 存储；每用户每日一份（唯一约束去重）；**任一素材采集失败不抛出**，
对应节置 null 并整体落 failed 状态（验收：生成失败不影响工作台）。

v1 为规则聚合（分节计数）；LLM 摘要生成后接（模型只负责解释，数字可追溯）。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select

from app.core.timezone import local_day_start_utc, now_local
from app.models.agent_briefing import AgentDailyBriefing
from app.models.agent_inbox import AgentInboxItem
from app.models.focus import FocusSession
from app.models.learning import WrongAnswer
from app.models.community import CommunityPost
from app.models.task import TaskClaim
from app.repositories.agent_briefing_repo import AgentBriefingRepository


class AgentBriefingService:
    def __init__(self, db, audit=None):
        self.db = db
        self.repo = AgentBriefingRepository(db)
        self.audit = audit

    async def get_or_generate(
        self, user_id: int, brief_date: Optional[date] = None
    ) -> AgentDailyBriefing:
        """工作台读路径：当日已有则返回，否则生成（去重 + 失败不抛出）。"""
        day = brief_date or now_local().date()
        existing = await self.repo.get_by_date(user_id, day)
        if existing is not None:
            return existing
        return await self._generate(user_id, day)

    async def _generate(self, user_id: int, day: date) -> AgentDailyBriefing:
        """素材窗口采集 + 聚合入库。任一分节失败置 null，整体落 failed。"""
        start = local_day_start_utc(day)
        end = local_day_start_utc(day + timedelta(days=1))
        content: dict = {}
        failed = False
        for key, collector in (
            ("reviews", lambda: self._collect_reviews(user_id, end)),
            ("focusMinutes", lambda: self._collect_focus(user_id, start, end)),
            ("tasks", lambda: self._collect_tasks(user_id)),
            ("community", lambda: self._collect_community(start, end)),
            ("inboxPending", lambda: self._collect_inbox(user_id)),
        ):
            try:
                content[key] = await collector()
            except Exception:  # noqa: BLE001 — 单节失败不阻断简报（验收标准）
                content[key] = None
                failed = True
        status = "failed" if failed else "ready"
        return await self.repo.create(
            {
                "user_id": user_id,
                "brief_date": day,
                "content": content,
                "status": status,
            }
        )

    # ------------------------------------------------------------------ 素材

    async def _collect_reviews(self, user_id: int, end) -> int:
        """到期复习数：错题本 review_due_at ≤ 今日窗口结束。"""
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(WrongAnswer)
                    .where(
                        WrongAnswer.user_id == user_id,
                        WrongAnswer.review_due_at <= end,
                    )
                )
            ).scalar_one()
        )

    async def _collect_focus(self, user_id: int, start, end) -> int:
        """当日专注分钟（FocusSession.duration_seconds 求和折算）。"""
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

    async def _collect_tasks(self, user_id: int) -> int:
        """进行中认领数（claimed / submitted）。"""
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(TaskClaim)
                    .where(
                        TaskClaim.user_id == user_id,
                        TaskClaim.status.in_(["claimed", "submitted"]),
                    )
                )
            ).scalar_one()
        )

    async def _collect_community(self, start, end) -> int:
        """当日社区新帖（published）。"""
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

    async def _collect_inbox(self, user_id: int) -> int:
        """待处理建议数。"""
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(AgentInboxItem)
                    .where(
                        AgentInboxItem.user_id == user_id,
                        AgentInboxItem.status == "pending",
                    )
                )
            ).scalar_one()
        )
