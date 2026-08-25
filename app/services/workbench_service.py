"""Workbench 业务服务：番茄钟专注记录 + 用户 LLM 配置。

写操作收敛到服务层（repo 只 flush、service 显式 commit），路由不再直写 db，
满足 Onboarding §B.1 分层单向与「service 显式 commit」约束。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.timezone import now_utc
from app.core.totp_encryption import encrypt_secret
from app.models.focus import FocusSession
from app.models.llm_config import LlmConfig


class WorkbenchService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def record_focus_session(
        self,
        user_id: int,
        duration_seconds: int,
        phase: str,
        sound_source: Optional[str],
    ) -> int:
        """番茄钟完成一轮专注后上报记录（幂等不校验重复，前端只报完成轮）。返回新记录 id。"""
        now = now_utc()
        session = FocusSession(
            user_id=user_id,
            duration_seconds=duration_seconds,
            phase=phase,
            sound_source=sound_source,
            started_at=now - timedelta(seconds=duration_seconds),
        )
        self.db.add(session)
        await self.db.commit()
        return session.id

    async def upsert_llm_config(
        self,
        user_id: int,
        provider: str,
        model: Optional[str],
        base_url: Optional[str],
        api_key: Optional[str],
        web_search_enabled: bool = True,
        trajectory_enabled: bool = True,
    ) -> dict:
        """保存用户 LLM 配置（API Key AES-256-GCM 加密存储，绝不落明文/日志）。返回配置状态摘要。"""
        cfg = (
            await self.db.execute(select(LlmConfig).where(LlmConfig.user_id == user_id))
        ).scalar_one_or_none()
        if cfg is None:
            cfg = LlmConfig(user_id=user_id)
            self.db.add(cfg)

        cfg.provider = provider
        cfg.model = model or settings.LLM_MODEL
        cfg.base_url = (base_url or "").strip() or None
        cfg.web_search_enabled = web_search_enabled
        cfg.trajectory_enabled = trajectory_enabled
        if api_key and api_key.strip():
            cfg.api_key_encrypted = encrypt_secret(api_key.strip())
        cfg.updated_at = now_utc()
        await self.db.commit()

        return {
            "ok": True,
            "configured": bool(cfg.api_key_encrypted),
            "provider": cfg.provider,
            "model": cfg.model,
            "webSearchEnabled": cfg.web_search_enabled,
            "trajectoryEnabled": cfg.trajectory_enabled,
        }
