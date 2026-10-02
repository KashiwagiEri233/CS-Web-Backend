"""Agent 建议收件箱服务（AG-P3-01）。

职责：建议项的产生（供 AG-P3-05 触发器 / AG-P3-06 调度调用）、用户收件箱
读取（惰性回收 snooze 过期）与状态机流转。

状态机：pending -> accepted | dismissed | snoozed；snoozed 到期自动回 pending；
pending 过期转 expired。终态（accepted/dismissed/expired）不可再流转。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from app.core.exceptions import AuthorizationException, NotFoundException
from app.core.timezone import now_utc
from app.models.agent_inbox import AgentInboxItem
from app.models.user import User
from app.repositories.agent_inbox_repo import AgentInboxRepository

# 建议类型开放集合：随 AG-P3 各条目扩充；未注册类型在创建时拒绝
INBOX_ITEM_TYPES = frozenset(
    {
        "review_due",  # 错题复习到期（AG-P2-03 联动）
        "resource_recommend",  # 资源推荐（AG-P2-06 联动）
        "goal_nudge",  # 学习目标进度提醒
        "community_digest",  # 社区新鲜事（AG-P4-06 联动）
        "system_hint",  # 系统提示
    }
)

INBOX_SOURCES = frozenset({"auxilio", "exam", "community", "github", "scheduler"})

# 状态流转表：仅 pending 可被用户处理；snooze 到期由 promote_due_snoozes 回到 pending
_ALLOWED_ACTIONS = {"accept": "accepted", "dismiss": "dismissed", "snooze": "snoozed"}
_SNOOZE_CAP_MINUTES = 60 * 24 * 7  # 单次稍后处理上限 7 天


class AgentInboxService:
    def __init__(self, db, audit=None):
        self.db = db
        self.repo = AgentInboxRepository(db)
        self.audit = audit

    # ------------------------------------------------------------------ 产生

    async def create_suggestion(
        self,
        user_id: int,
        *,
        type: str,
        source: str,
        title: str,
        idempotency_key: str,
        reason: Optional[str] = None,
        confidence: Optional[float] = None,
        estimated_minutes: Optional[int] = None,
        payload: Optional[dict] = None,
        expires_in_minutes: Optional[int] = None,
    ) -> tuple[AgentInboxItem, bool]:
        """创建建议项（幂等）：同 (user_id, idempotency_key) 已存在则原样返回。

        返回 (item, created)。类型/来源必须在注册集合内；confidence 限 0~1；
        过期时间由调用方以分钟数声明，写入 expires_at。
        """
        if type not in INBOX_ITEM_TYPES:
            raise ValueError(f"未注册的建议类型: {type}")
        if source not in INBOX_SOURCES:
            raise ValueError(f"未注册的建议来源: {source}")
        if confidence is not None and not (0.0 <= confidence <= 1.0):
            raise ValueError("confidence 必须在 0.0~1.0 之间")

        existing = await self.repo.find_by_idempotency_key(user_id, idempotency_key)
        if existing is not None:
            return existing, False

        expires_at = (
            now_utc() + timedelta(minutes=expires_in_minutes)
            if expires_in_minutes
            else None
        )
        item = await self.repo.create(
            {
                "user_id": user_id,
                "idempotency_key": idempotency_key,
                "type": type,
                "source": source,
                "title": title,
                "reason": reason,
                "confidence": confidence,
                "estimated_minutes": estimated_minutes,
                "payload": payload,
                "status": "pending",
                "expires_at": expires_at,
            }
        )
        await self.db.commit()
        return item, True

    # ------------------------------------------------------------------ 读取

    async def list_inbox(
        self,
        user: User,
        *,
        status: Optional[str] = None,
        type: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[AgentInboxItem], int]:
        """用户收件箱：先惰性回收（snooze 到期 / pending 过期）再查询。"""
        now = now_utc()
        await self.repo.promote_due_snoozes(user.id, now)
        await self.repo.expire_stale(user.id, now)
        await self.db.commit()
        return await self.repo.list_for_user(
            user.id, status=status, type=type, skip=skip, limit=limit
        )

    # ------------------------------------------------------------------ 处理

    async def update_status(
        self,
        user: User,
        item_id: int,
        action: str,
        snooze_minutes: Optional[int] = None,
    ) -> AgentInboxItem:
        """用户处理建议：accept / dismiss / snooze（所有权 + 状态机校验）。"""
        if action not in _ALLOWED_ACTIONS:
            raise ValueError(f"未知的处理动作: {action}")
        item = await self.repo.get_by_id(item_id)
        if item is None:
            raise NotFoundException(
                message="建议不存在",
                resource_type="agent_inbox_item",
                resource_id=str(item_id),
            )
        if item.user_id != user.id:
            raise AuthorizationException(message="无权操作他人的建议")
        if item.status != "pending":
            raise ValueError(f"当前状态 {item.status} 不可处理（仅 pending 可处理）")

        now = now_utc()
        item.status = _ALLOWED_ACTIONS[action]
        item.resolved_at = now
        if action == "snooze":
            minutes = min(snooze_minutes or 60, _SNOOZE_CAP_MINUTES)
            item.snoozed_until = now + timedelta(minutes=minutes)
            item.resolved_at = None  # snooze 非终态，到期回 pending 后可再处理
        await self.db.commit()
        return item
