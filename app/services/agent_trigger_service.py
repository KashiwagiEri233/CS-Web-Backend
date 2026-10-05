"""Agent 事件触发引擎（AG-P3-05）。

评估启用的自动化规则（AG-P3-02），经裁决器放行后生成收件箱建议：
    规则扫描 → arbitrate（静音/冷却/水位）→ 素材信号采集 → create_suggestion
    （幂等键 `rule:{id}:{yyyymmdd}`，与 AG-P3-01 联动去重）→ mark_fired

验收约束：冷却期/去重键 → 不会反复生成同一建议；单条规则失败不影响其他规则。
素材采集器 v1 覆盖 review_due / resource_new / goal_stalled；
community_match / exam_finished 随对应域事件接入（引擎按 None 信号优雅跳过）。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select

from app.core.loguru_logger import get_logger
from app.core.timezone import now_utc
from app.models.agent_automation import AgentAutomationRule
from app.models.exam import ExamAttempt
from app.models.focus import FocusSession
from app.models.learning import WrongAnswer
from app.models.learning_goal import LearningGoal
from app.models.resource import Resource
from app.repositories.agent_automation_repo import AgentAutomationRuleRepository
from app.services.agent_automation_service import AgentAutomationService
from app.services.agent_inbox_service import AgentInboxService

logger = get_logger("agent.trigger")

# 触发类型 → 收件箱建议类型（AG-P3-01 白名单子集映射）
TRIGGER_TO_INBOX_TYPE = {
    "review_due": "review_due",
    "resource_new": "resource_recommend",
    "goal_stalled": "goal_nudge",
    "community_match": "community_digest",
    "exam_finished": "system_hint",
}

# 各类型建议的默认标题模板（action_payload.title 可覆盖）
DEFAULT_TITLES = {
    "review_due": "有到期错题等待复习",
    "resource_new": "社区有新资源与你的学习方向相关",
    "goal_stalled": "学习目标出现停滞，看看计划",
    "community_match": "社区有与你相关的新讨论",
    "exam_finished": "考试结束，看看表现与薄弱点",
}


class AgentTriggerService:
    def __init__(self, db, audit=None):
        self.db = db
        self.rule_repo = AgentAutomationRuleRepository(db)
        self.automation = AgentAutomationService(db)
        self.inbox = AgentInboxService(db)
        self.audit = audit

    async def scan_enabled_rules(self) -> dict[str, int]:
        """扫描所有启用的规则并逐条评估（cron 入口）。

        单条规则失败仅记日志，不阻断其他规则。返回计数摘要。
        """
        enabled = (
            (
                await self.db.execute(
                    select(AgentAutomationRule).where(
                        AgentAutomationRule.enabled.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        created = skipped_arbitrated = skipped_no_signal = failed = 0
        for rule in enabled:
            try:
                ok, reason = await self.evaluate_rule(rule)
                if ok:
                    created += 1
                elif reason == "no_signal":
                    skipped_no_signal += 1
                else:
                    skipped_arbitrated += 1
            except Exception as exc:  # noqa: BLE001 — 单规则失败不阻断扫描
                failed += 1
                logger.warning("触发规则评估失败", rule_id=rule.id, error=str(exc))
        return {
            "scanned": len(enabled),
            "created": created,
            "gated": skipped_arbitrated,
            "no_signal": skipped_no_signal,
            "failed": failed,
        }

    async def evaluate_rule(self, rule: AgentAutomationRule) -> tuple[bool, str]:
        """评估单条规则：裁决 → 信号 → 建议入库。返回 (是否生成建议, 原因)。"""
        now = now_utc()
        allowed, gate_reason = await self.automation.arbitrate(rule, now=now)
        if not allowed:
            return False, gate_reason

        signal = await self._collect_signal(rule, now)
        if signal is None:
            return False, "no_signal"
        count, evidence = signal
        if count <= 0:
            return False, "no_signal"

        idempotency_key = f"rule:{rule.id}:{now:%Y%m%d}"
        item, created = await self.inbox.create_suggestion(
            rule.user_id,
            type=TRIGGER_TO_INBOX_TYPE.get(rule.trigger_type, "system_hint"),
            source="scheduler",
            title=(rule.action_payload or {}).get("title")
            or DEFAULT_TITLES.get(rule.trigger_type, rule.name),
            idempotency_key=idempotency_key,
            reason=evidence,
            confidence=None,
            payload={
                "ruleId": rule.id,
                "triggerType": rule.trigger_type,
                "count": count,
            },
            expires_in_minutes=60 * 24,
        )
        if created:
            await self.automation.mark_fired(rule.id)
            logger.info(
                "触发建议已生成",
                rule_id=rule.id,
                user_id=rule.user_id,
                count=count,
            )
        return created, ("created" if created else "dedup")

    # ------------------------------------------------------------------ 素材信号

    async def _collect_signal(
        self, rule: AgentAutomationRule, now
    ) -> Optional[tuple[int, str]]:
        """按触发类型采集信号：返回 (计数, 证据文本) 或 None（采集器未实现）。"""
        condition = rule.condition or {}
        if rule.trigger_type == "review_due":
            count = int(
                (
                    await self.db.execute(
                        select(func.count())
                        .select_from(WrongAnswer)
                        .where(
                            WrongAnswer.user_id == rule.user_id,
                            WrongAnswer.review_due_at <= now,
                        )
                    )
                ).scalar_one()
            )
            return count, f"错题本中有 {count} 条复习已到期"
        if rule.trigger_type == "resource_new":
            window = now - timedelta(hours=24)
            stmt = (
                select(func.count())
                .select_from(Resource)
                .where(
                    Resource.status == "approved",
                    Resource.created_at >= window,
                    Resource.submitted_by != rule.user_id,
                )
            )
            tag = condition.get("techTag")
            if tag:
                stmt = stmt.where(Resource.tech_tags.contains([tag]))
            count = int((await self.db.execute(stmt)).scalar_one())
            suffix = f"（标签 {tag}）" if tag else ""
            return count, f"近 24 小时新增 {count} 条已审核资源{suffix}"
        if rule.trigger_type == "goal_stalled":
            days = int(condition.get("days") or 7)
            active_goals = int(
                (
                    await self.db.execute(
                        select(func.count())
                        .select_from(LearningGoal)
                        .where(
                            LearningGoal.user_id == rule.user_id,
                            LearningGoal.status == "active",
                        )
                    )
                ).scalar_one()
            )
            if active_goals == 0:
                return 0, ""
            last_focus = (
                await self.db.execute(
                    select(func.max(FocusSession.created_at)).where(
                        FocusSession.user_id == rule.user_id
                    )
                )
            ).scalar_one()
            stalled = last_focus is None or last_focus < now - timedelta(days=days)
            return (
                (active_goals, f"{active_goals} 个进行中目标已 {days} 天无专注记录")
                if stalled
                else (0, "")
            )
        if rule.trigger_type == "exam_finished":
            # 考试完成事件随考试域会话模型接入；v1 优雅跳过
            int(
                (
                    await self.db.execute(
                        select(func.count())
                        .select_from(ExamAttempt)
                        .where(ExamAttempt.user_id == rule.user_id)
                    )
                ).scalar_one()
            )
            return None
        return None
