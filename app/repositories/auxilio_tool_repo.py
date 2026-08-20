"""Auxilio 工具查询仓储（只读）：学习助手 Skills 的数据访问层。

将原先散落在 `auxilio_agent.execute_tool` 内的直连 SQL 收敛到本仓储，
SQL 语义与重构前完全一致（仅迁移位置，不改变行为）。
"""

from __future__ import annotations

from typing import Optional

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc, local_day_start_utc
from app.models.api_usage import ApiCallLog
from app.models.exam import Exam
from app.models.focus import FocusSession
from app.models.llm_usage import LlmUsageLog
from app.models.resource import Resource
from app.models.task import Task, TaskClaim


class AuxilioToolRepository:
    """学习助手工具查询仓储（只读查询，无写入）。"""

    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db

    async def upcoming_exams(self, limit: int = 3) -> list[Exam]:
        """最近进行中的考试（已发布且未结束，按截止时间升序）。"""
        now = now_utc()
        rows = await self.db.execute(
            select(Exam)
            .where(Exam.status == "published", Exam.end_time > now)
            .order_by(Exam.end_time.asc())
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def published_tasks(self, limit: int = 10) -> list[Task]:
        """已发布的协会任务（按创建时间倒序）。"""
        rows = await self.db.execute(
            select(Task)
            .where(Task.status == "published")
            .order_by(Task.created_at.desc())
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def my_claims(
        self, user_id: int, limit: int = 10
    ) -> list[tuple[Task, TaskClaim]]:
        """用户已认领的任务（按认领时间倒序）。"""
        rows = await self.db.execute(
            select(Task, TaskClaim)
            .join(TaskClaim, TaskClaim.task_id == Task.id)
            .where(TaskClaim.user_id == user_id)
            .order_by(TaskClaim.created_at.desc())
            .limit(limit)
        )
        return list(rows.tuples().all())

    async def search_resources(self, keyword: str, limit: int = 5) -> list[Resource]:
        """按标题或描述模糊搜索已审核的学习资源（按浏览量倒序）。

        统一实现（重复实现治理波次 A1）：全站搜索 search_service 与学习助手
        web_search/search_resources 工具均透传本方法，保证同一关键词结果一致。
        """
        # 转义 LIKE 通配符，避免用户输入中的 % / _ 被当作模式
        escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        rows = await self.db.execute(
            select(Resource)
            .where(
                Resource.status == "approved",
                or_(
                    Resource.title.ilike(like, escape="\\"),
                    Resource.description.ilike(like, escape="\\"),
                ),
            )
            .order_by(Resource.view_count.desc())
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def llm_usage_stats(self, user_id: int) -> dict[str, int]:
        """LLM 调用用量统计（累计 + 今日），单次聚合查询。"""
        today_start = local_day_start_utc()
        row = (
            await self.db.execute(
                select(
                    func.count().label("total_calls"),
                    func.coalesce(func.sum(LlmUsageLog.total_tokens), 0).label(
                        "total_tokens"
                    ),
                    # FILTER 子句：仅统计今日记录，与全量聚合同扫一次表
                    func.count()
                    .filter(LlmUsageLog.created_at >= today_start)
                    .label("today_calls"),
                ).where(LlmUsageLog.user_id == user_id)
            )
        ).one()
        return {
            "total_calls": int(row.total_calls),
            "today_calls": int(row.today_calls),
            "total_tokens": int(row.total_tokens),
        }

    async def llm_usage_today_tokens(self, user_id: int) -> int:
        """用户今日累计消耗 token（用于每日预算拦截）。"""
        today_start = local_day_start_utc()
        total = (
            await self.db.execute(
                select(func.coalesce(func.sum(LlmUsageLog.total_tokens), 0)).where(
                    LlmUsageLog.user_id == user_id,
                    LlmUsageLog.created_at >= today_start,
                )
            )
        ).scalar_one()
        return int(total)

    async def api_usage_stats(self, user_id: Optional[int] = None) -> dict[str, int]:
        """API 调用统计（今日 + 近 30 天）。

        user_id 为 None 时返回全站聚合（管理员可观测性）；传入时仅统计该用户，
        避免普通用户经学习助手工具越权获取全站用量（ER-18）。
        原全站行为在 user_id=None 时完全保留。
        """
        today_start = local_day_start_utc()
        since = today_start - timedelta(days=29)
        base = select(func.count())
        if user_id is not None:
            base = base.where(ApiCallLog.user_id == user_id)
        total = (
            await self.db.execute(base.where(ApiCallLog.created_at >= since))
        ).scalar_one()
        today = (
            await self.db.execute(base.where(ApiCallLog.created_at >= today_start))
        ).scalar_one()
        return {"today": int(today), "last_30_days_total": int(total)}

    async def pomodoro_stats(self, user_id: int) -> dict[str, int]:
        """番茄钟专注统计（累计专注次数 + 今日专注分钟）。"""
        today_start = local_day_start_utc()
        total_sessions = (
            await self.db.execute(
                select(func.count()).where(
                    FocusSession.user_id == user_id,
                    FocusSession.phase == "focus",
                )
            )
        ).scalar_one()
        today_minutes = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(FocusSession.duration_seconds), 0) / 60.0
                ).where(
                    FocusSession.user_id == user_id,
                    FocusSession.phase == "focus",
                    FocusSession.created_at >= today_start,
                )
            )
        ).scalar_one()
        return {
            "total_focus_sessions": int(total_sessions),
            "today_focus_minutes": round(today_minutes),
        }
