"""Agent 自动化规则服务（AG-P3-02）：CRUD + 防打扰裁决器。

裁决器移植 Aervox CR-032 / CAP-030 的三参数模型（RootDoc-AgentEval.md §2）：
1. **冷却**（cooldown_minutes）：同一规则两次放行的最小间隔；
2. **静音时段**（quiet_hours_start/end）：区间内一律压制，支持跨午夜；
3. **每小时频次水位**（max_per_hour）：按收件箱建议幂等键前缀 `rule:{id}:`
   统计最近 1 小时放行数，超水位压制。

「一键熔断」由两层承担：规则级 `enabled`（逐条启停，默认 False）与
全局 `AGENT_SWEEPS_ENABLED`（AG-P3-06）；用户级总熔断随 AG-P3-07 投递策略设计。
触发器（AG-P3-05）产生建议前 MUST 调用 `arbitrate()` 放行。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from app.core.exceptions import AuthorizationException, NotFoundException
from app.core.timezone import now_utc
from app.models.agent_automation import AgentAutomationRule
from app.models.user import User
from app.repositories.agent_automation_repo import AgentAutomationRuleRepository

# 触发类型白名单：与 AG-P3-05 的触发器清单对齐（随实现扩充）
TRIGGER_TYPES = frozenset(
    {
        "review_due",  # 复习到期
        "exam_finished",  # 考试结束
        "goal_stalled",  # 目标停滞
        "community_match",  # 社区高相关内容
        "resource_new",  # 新资源匹配
    }
)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_MAX_PER_HOUR_LIMIT = 60


def quiet_hours_active(start: Optional[str], end: Optional[str], now_time) -> bool:
    """静音时段判定：支持跨午夜区间（如 22:00-07:00）。无配置返回 False。"""
    if not start or not end:
        return False
    if not (_TIME_RE.match(start) and _TIME_RE.match(end)):
        return False
    start_min = int(start[:2]) * 60 + int(start[3:])
    end_min = int(end[:2]) * 60 + int(end[3:])
    cur = now_time.hour * 60 + now_time.minute
    if start_min <= end_min:
        return start_min <= cur < end_min
    return cur >= start_min or cur < end_min


def in_cooldown(
    last_fired_at: Optional[datetime], cooldown_minutes: int, now: datetime
) -> bool:
    if last_fired_at is None or cooldown_minutes <= 0:
        return False
    return now < last_fired_at + timedelta(minutes=cooldown_minutes)


class AgentAutomationService:
    def __init__(self, db, audit=None):
        self.db = db
        self.repo = AgentAutomationRuleRepository(db)
        self.audit = audit

    # ------------------------------------------------------------------ CRUD

    async def create_rule(self, user: User, data: dict) -> AgentAutomationRule:
        """创建规则（默认 enabled=False；触发类型白名单 + 时间格式校验）。"""
        trigger_type = data.get("trigger_type")
        if trigger_type not in TRIGGER_TYPES:
            raise ValueError(f"未注册的触发类型: {trigger_type}")
        if data.get("action_type", "inbox_suggestion") != "inbox_suggestion":
            raise ValueError(f"未支持的动作类型: {data.get('action_type')}")
        self._validate_quiet_hours(
            data.get("quiet_hours_start"), data.get("quiet_hours_end")
        )
        max_per_hour = data.get("max_per_hour") or 3
        if not (1 <= max_per_hour <= _MAX_PER_HOUR_LIMIT):
            raise ValueError("max_per_hour 必须在 1~60 之间")
        rule = await self.repo.create(
            {
                "user_id": user.id,
                "name": data["name"],
                "trigger_type": trigger_type,
                "condition": data.get("condition"),
                "action_type": "inbox_suggestion",
                "action_payload": data.get("action_payload"),
                "quiet_hours_start": data.get("quiet_hours_start"),
                "quiet_hours_end": data.get("quiet_hours_end"),
                "cooldown_minutes": data.get("cooldown_minutes") or 240,
                "max_per_hour": max_per_hour,
                "enabled": False,
            }
        )
        await self.db.commit()
        return rule

    async def list_rules(
        self,
        user: User,
        *,
        enabled: Optional[bool] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[AgentAutomationRule], int]:
        return await self.repo.list_for_user(
            user.id, enabled=enabled, skip=skip, limit=limit
        )

    async def update_rule(
        self, user: User, rule_id: int, data: dict
    ) -> AgentAutomationRule:
        rule = await self._get_owned(user, rule_id)
        if "trigger_type" in data and data["trigger_type"] not in TRIGGER_TYPES:
            raise ValueError(f"未注册的触发类型: {data['trigger_type']}")
        if "quiet_hours_start" in data or "quiet_hours_end" in data:
            self._validate_quiet_hours(
                data.get("quiet_hours_start", rule.quiet_hours_start),
                data.get("quiet_hours_end", rule.quiet_hours_end),
            )
        if "max_per_hour" in data and not (
            1 <= data["max_per_hour"] <= _MAX_PER_HOUR_LIMIT
        ):
            raise ValueError("max_per_hour 必须在 1~60 之间")
        for field in (
            "name",
            "trigger_type",
            "condition",
            "action_payload",
            "quiet_hours_start",
            "quiet_hours_end",
            "cooldown_minutes",
            "max_per_hour",
        ):
            if field in data:
                setattr(rule, field, data[field])
        await self.db.commit()
        return rule

    async def set_enabled(
        self, user: User, rule_id: int, enabled: bool
    ) -> AgentAutomationRule:
        """逐条启停（默认不启用，由用户显式打开）。"""
        rule = await self._get_owned(user, rule_id)
        rule.enabled = enabled
        await self.db.commit()
        return rule

    async def delete_rule(self, user: User, rule_id: int) -> None:
        rule = await self._get_owned(user, rule_id)
        await self.db.delete(rule)
        await self.db.commit()

    # ------------------------------------------------------------------ 裁决器

    async def arbitrate(
        self, rule: AgentAutomationRule, *, now: Optional[datetime] = None
    ) -> tuple[bool, str]:
        """CR-032 三参数裁决：返回 (放行, 原因)。

        顺序：规则启停 → 静音时段 → 冷却 → 每小时频次水位。压制的建议不产生
        收件箱副作用；放行方（AG-P3-05 触发器）负责写 last_fired_at 与建议。
        """
        now = now or now_utc()
        if not rule.enabled:
            return False, "rule_disabled"
        local_now = now
        if quiet_hours_active(
            rule.quiet_hours_start, rule.quiet_hours_end, local_now.time()
        ):
            return False, "quiet_hours"
        if in_cooldown(rule.last_fired_at, rule.cooldown_minutes, now):
            return False, "cooldown"
        fired = await self.repo.count_fired_since(rule.id, now - timedelta(hours=1))
        if fired >= rule.max_per_hour:
            return False, "hourly_cap"
        return True, "allowed"

    async def mark_fired(self, rule_id: int) -> None:
        """放行后回写 last_fired_at（供冷却判定；由 AG-P3-05 触发器调用）。"""
        rule = await self.repo.get_by_id(rule_id)
        if rule is not None:
            rule.last_fired_at = now_utc()
            await self.db.commit()

    # ------------------------------------------------------------------ 内部

    async def _get_owned(self, user: User, rule_id: int) -> AgentAutomationRule:
        rule = await self.repo.get_by_id(rule_id)
        if rule is None:
            raise NotFoundException(
                message="规则不存在",
                resource_type="agent_automation_rule",
                resource_id=str(rule_id),
            )
        if rule.user_id != user.id:
            raise AuthorizationException(message="无权操作他人的规则")
        return rule

    @staticmethod
    def _validate_quiet_hours(start: Optional[str], end: Optional[str]) -> None:
        for v in (start, end):
            if v is not None and not _TIME_RE.match(v):
                raise ValueError(f"静音时段格式非法: {v}（期望 HH:MM）")
