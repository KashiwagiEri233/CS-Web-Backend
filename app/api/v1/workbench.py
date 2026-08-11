"""工作台 API：贡献热力图（GitHub）+ API 调用统计 + 番茄钟专注记录。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import WORKBENCH_MAX_DURATION_SECONDS
from app.core.timezone import local_to_utc, now_local
from app.dependencies import get_current_active_user
from app.dependencies import get_db
from app.middleware.rbac import require_admin_2fa
from app.models.api_usage import ApiCallLog
from app.models.focus import FocusSession
from app.models.llm_usage import LlmUsageLog
from app.models.user import User
from app.services.contribution_service import ContributionService
from app.services.workbench_service import WorkbenchService

router = APIRouter(prefix="/workbench", tags=["workbench"])


class FocusSessionIn(BaseModel):
    """前端完成一轮专注后的上报。"""

    duration_seconds: int = Field(gt=0, le=WORKBENCH_MAX_DURATION_SECONDS)
    phase: str = Field(default="focus", pattern="^(focus|shortBreak|longBreak)$")
    sound_source: Optional[str] = Field(default=None, max_length=40)


def _github_username(user: User) -> Optional[str]:
    """从用户资料提取 GitHub 用户名（github_url 形如 https://github.com/xxx）。"""
    url = user.github_url or ""
    url = url.rstrip("/")
    if not url:
        return None
    # 支持 https://github.com/xxx 与 https://github.com/xxx/ 以及裸用户名
    last = url.rsplit("/", 1)[-1]
    return last if last and last != "github.com" else None


def _local_today() -> date:
    """配置时区的今天（替代 ``date.today()``，避免服务器本地时区漂移）。"""
    return now_local().date()


def _local_day_start_utc(d: date) -> datetime:
    """配置时区某日的零点，转换为 UTC aware（存储层比较口径）。"""
    start = local_to_utc(datetime.combine(d, datetime.min.time()))
    assert start is not None  # 入参恒非 None
    return start


@router.get("/contributions/github")
async def get_github_contributions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    username: Optional[str] = Query(default=None, description="GitHub 用户名；缺省用绑定资料"),
    year: int = Query(default=0, ge=2015, le=2100),
    refresh: bool = Query(default=False, description="强制刷新"),
):
    """GitHub 贡献热力图（近一年数据，6h 缓存）。"""
    resolved = (username or "").strip() or _github_username(user)
    if not resolved:
        return {
            "ok": False,
            "need_username": True,
            "message": "请在 GitHub 设置中绑定用户名，或在请求中传入 username",
        }
    service = ContributionService(db)
    payload = await service.get_github(
        user_id=user.id,
        username=resolved,
        year=year or None,
        force_refresh=refresh,
    )
    return {"ok": True, **payload}


@router.get("/stats/api-usage")
async def get_api_usage_stats(
    db: AsyncSession = Depends(get_db),
    # ER-18 关联：全站 API 用量属管理员可观测性，强制管理员 + 2FA（与所有 admin 端点一致）。
    user: User = Depends(require_admin_2fa()),
    days: int = Query(default=30, ge=1, le=90),
):
    """API 调用统计：今日计数 + 近 N 天趋势 + endpoint 分布。"""
    today = _local_today()
    since = _local_day_start_utc(today - timedelta(days=days - 1))

    # 近 N 天按日聚合（按配置时区取日，与 today/since 口径一致）
    daily_rows = (
        await db.execute(
            select(
                func.date(func.timezone(settings.TIMEZONE, ApiCallLog.created_at)).label("d"),
                func.count().label("c"),
            )
            .where(ApiCallLog.created_at >= since)
            .group_by("d")
            .order_by("d")
        )
    ).all()

    # endpoint 分布 Top 10
    endpoint_rows = (
        await db.execute(
            select(ApiCallLog.endpoint, func.count().label("c"))
            .where(ApiCallLog.created_at >= since)
            .group_by(ApiCallLog.endpoint)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()

    # 今日统计
    today_start = _local_day_start_utc(today)
    today_total = (
        await db.execute(
            select(func.count()).where(ApiCallLog.created_at >= today_start)
        )
    ).scalar_one()
    today_errors = (
        await db.execute(
            select(func.count()).where(
                ApiCallLog.created_at >= today_start,
                ApiCallLog.status >= 400,
            )
        )
    ).scalar_one()
    avg_latency = (
        await db.execute(
            select(func.avg(ApiCallLog.latency_ms)).where(
                ApiCallLog.created_at >= today_start
            )
        )
    ).scalar_one()

    # 补齐空日（保证前端折线连续）
    by_day = {row.d: row.c for row in daily_rows}
    daily: list[dict] = []
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        daily.append({"date": d.isoformat(), "count": int(by_day.get(d, 0))})

    return {
        "ok": True,
        "days": days,
        "today": {
            "count": int(today_total),
            "errors": int(today_errors),
            "avgLatencyMs": round(float(avg_latency or 0)),
        },
        "daily": daily,
        "endpoints": [
            {"endpoint": row.endpoint, "count": int(row.c)} for row in endpoint_rows
        ],
    }


@router.post("/focus-sessions")
async def record_focus_session(
    payload: FocusSessionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """番茄钟完成一轮专注后上报记录（幂等不校验重复，前端只报完成轮）。"""
    session_id = await WorkbenchService(db).record_focus_session(
        user.id,
        payload.duration_seconds,
        payload.phase,
        payload.sound_source,
    )
    return {"ok": True, "id": session_id}


@router.get("/stats/pomodoro")
async def get_pomodoro_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    days: int = Query(default=30, ge=1, le=90),
):
    """番茄钟专注统计：总轮数 / 总时长 / 今日 / 近 N 天分布（喂给学习助手 Skill）。"""
    today = _local_today()
    since = _local_day_start_utc(today - timedelta(days=days - 1))

    total_sessions = (
        await db.execute(
            select(func.count()).where(
                FocusSession.user_id == user.id,
                FocusSession.phase == "focus",
            )
        )
    ).scalar_one()
    total_minutes = (
        await db.execute(
            select(func.coalesce(func.sum(FocusSession.duration_seconds), 0) / 60.0).where(
                FocusSession.user_id == user.id,
                FocusSession.phase == "focus",
            )
        )
    ).scalar_one()
    today_start = _local_day_start_utc(today)
    today_minutes = (
        await db.execute(
            select(func.coalesce(func.sum(FocusSession.duration_seconds), 0) / 60.0).where(
                FocusSession.user_id == user.id,
                FocusSession.phase == "focus",
                FocusSession.created_at >= today_start,
            )
        )
    ).scalar_one()

    # 近 N 天按日聚合专注分钟（按配置时区取日）
    daily_rows = (
        await db.execute(
            select(
                func.date(func.timezone(settings.TIMEZONE, FocusSession.created_at)).label("d"),
                (func.coalesce(func.sum(FocusSession.duration_seconds), 0) / 60.0).label("m"),
            )
            .where(
                FocusSession.user_id == user.id,
                FocusSession.phase == "focus",
                FocusSession.created_at >= since,
            )
            .group_by("d")
            .order_by("d")
        )
    ).all()
    by_day = {row.d: int(row.m) for row in daily_rows}
    daily: list[dict] = []
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        daily.append({"date": d.isoformat(), "minutes": int(by_day.get(d, 0))})

    return {
        "ok": True,
        "totalSessions": int(total_sessions),
        "totalMinutes": int(total_minutes),
        "todayMinutes": int(today_minutes),
        "daily": daily,
    }


# ---------------------------------------------------------------------------
# LLM 用量统计 + 用户级模型配置（自行接入 API Key）
# ---------------------------------------------------------------------------


@router.get("/stats/llm-usage")
async def get_llm_usage_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    days: int = Query(default=30, ge=1, le=90),
):
    """学习助手 LLM 用量：调用次数 / token 消耗 / 近 N 天趋势 / 模型分布。"""
    today = _local_today()
    since = _local_day_start_utc(today - timedelta(days=days - 1))

    # 总计
    total_calls = (
        await db.execute(
            select(func.count()).where(LlmUsageLog.user_id == user.id)
        )
    ).scalar_one()
    total_tokens = (
        await db.execute(
            select(func.coalesce(func.sum(LlmUsageLog.total_tokens), 0)).where(
                LlmUsageLog.user_id == user.id
            )
        )
    ).scalar_one()

    # 今日
    today_start = _local_day_start_utc(today)
    today_calls = (
        await db.execute(
            select(func.count()).where(
                LlmUsageLog.user_id == user.id,
                LlmUsageLog.created_at >= today_start,
            )
        )
    ).scalar_one()
    today_tokens = (
        await db.execute(
            select(func.coalesce(func.sum(LlmUsageLog.total_tokens), 0)).where(
                LlmUsageLog.user_id == user.id,
                LlmUsageLog.created_at >= today_start,
            )
        )
    ).scalar_one()
    avg_latency = (
        await db.execute(
            select(func.avg(LlmUsageLog.latency_ms)).where(
                LlmUsageLog.user_id == user.id,
                LlmUsageLog.created_at >= today_start,
            )
        )
    ).scalar_one()

    # 近 N 天按日聚合 tokens（按配置时区取日）
    daily_rows = (
        await db.execute(
            select(
                func.date(func.timezone(settings.TIMEZONE, LlmUsageLog.created_at)).label("d"),
                func.coalesce(func.sum(LlmUsageLog.total_tokens), 0).label("tk"),
                func.count().label("c"),
            )
            .where(
                LlmUsageLog.user_id == user.id,
                LlmUsageLog.created_at >= since,
            )
            .group_by("d")
            .order_by("d")
        )
    ).all()
    by_day = {row.d: row for row in daily_rows}
    daily: list[dict] = []
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        row = by_day.get(d)
        daily.append(
            {
                "date": d.isoformat(),
                "tokens": int(row.tk) if row else 0,
                "calls": int(row.c) if row else 0,
            }
        )

    # 模型分布
    model_rows = (
        await db.execute(
            select(LlmUsageLog.model, func.count().label("c"))
            .where(LlmUsageLog.user_id == user.id)
            .group_by(LlmUsageLog.model)
            .order_by(func.count().desc())
            .limit(6)
        )
    ).all()

    return {
        "ok": True,
        "days": days,
        "today": {
            "calls": int(today_calls),
            "tokens": int(today_tokens),
            "avgLatencyMs": round(float(avg_latency or 0)),
        },
        "totalCalls": int(total_calls),
        "totalTokens": int(total_tokens),
        "daily": daily,
        "models": [{"model": row.model, "count": int(row.c)} for row in model_rows],
    }


class LlmConfigIn(BaseModel):
    """用户 LLM 配置（api_key 留空表示保留原值）。"""

    provider: str = Field(default="openai", pattern="^(openai|anthropic)$")
    api_key: Optional[str] = Field(default=None, max_length=300)
    base_url: Optional[str] = Field(default=None, max_length=300)
    model: str = Field(default="gpt-4o-mini", max_length=120)


@router.get("/llm-config")
async def get_llm_config(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """读取用户 LLM 配置（脱敏：apiKey 只回显掩码，不回传明文）。"""
    from app.models.llm_config import LlmConfig

    cfg = (
        await db.execute(select(LlmConfig).where(LlmConfig.user_id == user.id))
    ).scalar_one_or_none()
    if cfg is None:
        return {"ok": True, "configured": False}
    return {
        "ok": True,
        "configured": bool(cfg.api_key_encrypted),
        "provider": cfg.provider,
        "baseUrl": cfg.base_url,
        "model": cfg.model,
        # 掩码回显（前 4 后 4），便于前端感知已配置
        "apiKeyMasked": _mask_secret(cfg.api_key_encrypted),
    }


def _mask_secret(encrypted: str | None) -> str:
    if not encrypted:
        return ""
    try:
        from app.core.totp_encryption import decrypt_secret

        plain = decrypt_secret(encrypted)
    except ValueError:
        return ""
    if len(plain) <= 8:
        return "****"
    return f"{plain[:4]}…{plain[-4:]}"


@router.put("/llm-config")
async def update_llm_config(
    payload: LlmConfigIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """保存用户 LLM 配置（API Key AES-256-GCM 加密存储，绝不落明文/日志）。"""
    return await WorkbenchService(db).upsert_llm_config(
        user.id,
        payload.provider,
        payload.model,
        payload.base_url,
        payload.api_key,
    )
