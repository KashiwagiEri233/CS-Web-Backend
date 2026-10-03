"""积分 API。

TOOLS-GOV Slice A（2026-09-14）：解除模块级 mypy 忽略指令，路由对齐 service
真实实现（profile/get_history/leaderboard），出参挂载既有的 ``PointsProfileOut``
/ ``LeaderboardEntry`` schema（snake_case，与前端 BFF 现读键一致；全站
camelCase 二期统一见待办 P1-8b）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.dependencies import get_current_active_user
from app.dependencies_services import get_points_service
from app.models.user import User
from app.schemas.tools import LeaderboardEntry, PointsProfileOut
from app.services.points_service import PointsService

router = APIRouter()


@router.get("/points/me", response_model=PointsProfileOut)
async def my_points(
    service: PointsService = Depends(get_points_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """我的积分档案（余额/等级 + 最近流水）。"""
    return await service.profile(current_user.id)


@router.get("/points/me/history")
async def my_history(
    skip: int = 0,
    limit: int = 50,
    service: PointsService = Depends(get_points_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """积分流水分页（时间倒序）。"""
    records = await service.get_history(current_user.id, skip=skip, limit=limit)
    return {"records": records}


@router.get("/points/leaderboard", response_model=list[LeaderboardEntry])
async def leaderboard(
    skip: int = 0,
    limit: int = 50,
    service: PointsService = Depends(get_points_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """积分排行榜（按余额倒序，limit 控制返回条数）。"""
    return await service.leaderboard(top_n=max(1, limit))
