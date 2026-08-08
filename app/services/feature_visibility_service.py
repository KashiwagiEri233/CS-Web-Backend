"""功能模块可见性 — 服务层。

复用 settings 表（module="feature_visibility"），每行一个模块，value 存
JSON 序列化的三态布尔。未配置的模块回退到默认值（与改造前硬编码行为一致），
保证首次读取为空时整站导航不消失（fail-open）。

事务边界：本服务只 flush，由路由层通过 AuditService.record_atomic 统一提交，
确保业务变更与审计记录同事务原子落库。
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.setting import Setting
from app.schemas.feature_visibility import (
    FeatureVisibilityConfig,
    ModuleVisibility,
    VisibilityRule,
)

MODULE = "feature_visibility"

# 受管组件及其默认可见性（fail-open：未知组件默认可见，保证可用性）。
# 覆盖全站前端组件：页面路由 / 框架组件 / 工作台 widget / 工具子功能 / 社区子功能。
# community 作为独立页面重新纳入受管（此前方案误并入 tools）。
DEFAULT_MODULES: dict[str, VisibilityRule] = {
    # ===== 页面路由（route-level modules）=====
    "home": VisibilityRule(guest=True, member=True, admin=True),
    "about": VisibilityRule(guest=True, member=True, admin=True),
    "events": VisibilityRule(guest=True, member=True, admin=True),
    "tools": VisibilityRule(guest=False, member=True, admin=True),
    "community": VisibilityRule(guest=True, member=True, admin=True),
    "profile": VisibilityRule(guest=False, member=True, admin=True),
    "notifications": VisibilityRule(guest=False, member=True, admin=True),
    "join": VisibilityRule(guest=True, member=True, admin=True),
    "admin": VisibilityRule(guest=False, member=False, admin=True),
    # ===== 框架组件（layout / chrome）=====
    "chrome-navbar": VisibilityRule(guest=True, member=True, admin=True),
    "chrome-announcement-banner": VisibilityRule(guest=True, member=True, admin=True),
    "chrome-footer": VisibilityRule(guest=True, member=True, admin=True),
    "chrome-theme-toggle": VisibilityRule(guest=True, member=True, admin=True),
    "chrome-user-menu": VisibilityRule(guest=True, member=True, admin=True),
    "chrome-language-switcher": VisibilityRule(guest=True, member=True, admin=True),
    # ===== 工作台 widget =====
    "wb-greeting": VisibilityRule(guest=True, member=True, admin=True),
    "wb-today-tasks": VisibilityRule(guest=True, member=True, admin=True),
    "wb-github-heatmap": VisibilityRule(guest=True, member=True, admin=True),
    "wb-llm-usage": VisibilityRule(guest=True, member=True, admin=True),
    "wb-quick-notes": VisibilityRule(guest=True, member=True, admin=True),
    "wb-pomodoro": VisibilityRule(guest=True, member=True, admin=True),
    "wb-exam-countdown": VisibilityRule(guest=True, member=True, admin=True),
    "wb-assistant-chat": VisibilityRule(guest=True, member=True, admin=True),
    # ===== 工具子功能（/tools 卡片）=====
    "tools-exam": VisibilityRule(guest=True, member=True, admin=True),
    "tools-resource": VisibilityRule(guest=True, member=True, admin=True),
    "tools-auxilio": VisibilityRule(guest=True, member=True, admin=True),
    "tools-task": VisibilityRule(guest=True, member=True, admin=True),
    "tools-dev-center": VisibilityRule(guest=True, member=True, admin=True),
    "tools-admin-panel": VisibilityRule(guest=False, member=False, admin=True),
    # ===== 社区子功能（/community 区块）=====
    "community-feed": VisibilityRule(guest=True, member=True, admin=True),
    "community-sidebar-nav": VisibilityRule(guest=True, member=True, admin=True),
    "community-sidebar-trending": VisibilityRule(guest=True, member=True, admin=True),
    "community-featured": VisibilityRule(guest=True, member=True, admin=True),
    "community-search": VisibilityRule(guest=True, member=True, admin=True),
    "community-tags": VisibilityRule(guest=True, member=True, admin=True),
    "community-mine": VisibilityRule(guest=False, member=True, admin=True),
    "community-admin": VisibilityRule(guest=False, member=False, admin=True),
}

#: 已知组件标识集合（供路由层校验路径参数）。
KNOWN_MODULE_KEYS: frozenset[str] = frozenset(DEFAULT_MODULES.keys())


def _rule_to_json(rule: VisibilityRule) -> str:
    return json.dumps({"guest": rule.guest, "member": rule.member, "admin": rule.admin})


def _parse_rule(raw: str) -> Optional[VisibilityRule]:
    try:
        data = json.loads(raw)
        return VisibilityRule(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


class FeatureVisibilityService:
    """功能模块可见性读写。repo 只 flush，路由层统一 commit。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _load_all_stored(self) -> dict[str, VisibilityRule]:
        stmt = select(Setting).where(Setting.module == MODULE)
        rows = await self.db.execute(stmt)
        stored: dict[str, VisibilityRule] = {}
        for row in rows.scalars().all():
            rule = _parse_rule(row.value)
            if rule is not None:
                stored[row.key] = rule
        return stored

    async def get_config(self) -> FeatureVisibilityConfig:
        """返回全部受管模块的可见性（缺失项回退默认值）。"""
        stored = await self._load_all_stored()
        modules: list[ModuleVisibility] = []
        for key in DEFAULT_MODULES:
            rule = stored.get(key, DEFAULT_MODULES[key])
            modules.append(
                ModuleVisibility(
                    module_key=key,
                    guest=rule.guest,
                    member=rule.member,
                    admin=rule.admin,
                )
            )
        return FeatureVisibilityConfig(modules=modules)

    async def get_rule(self, module_key: str) -> Optional[VisibilityRule]:
        """读取单模块规则；未知模块返回 None，已知但未配置返回默认值。"""
        if module_key not in DEFAULT_MODULES:
            return None
        stmt = select(Setting).where(Setting.module == MODULE, Setting.key == module_key)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            return DEFAULT_MODULES[module_key]
        return _parse_rule(row.value) or DEFAULT_MODULES[module_key]

    async def update_module(
        self, module_key: str, rule: VisibilityRule
    ) -> tuple[VisibilityRule, ModuleVisibility]:
        """更新单模块可见性（只 flush，不 commit）。返回 (旧规则, 新模块视图)。"""
        old = await self.get_rule(module_key)
        # 调用方已校验 module_key 合法，此处 old 不会为 None。
        value = _rule_to_json(rule)
        stmt = select(Setting).where(Setting.module == MODULE, Setting.key == module_key)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            self.db.add(Setting(module=MODULE, key=module_key, value=value))
        else:
            row.value = value
            row.updated_at = now_utc()
        await self.db.flush()
        new = ModuleVisibility(
            module_key=module_key,
            guest=rule.guest,
            member=rule.member,
            admin=rule.admin,
        )
        return old if old is not None else rule, new
