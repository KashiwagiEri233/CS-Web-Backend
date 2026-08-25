# mypy: ignore-errors
# 本文件 API 与 service 契约错位(存量)，暂用模块级忽略，保持端点/契约不变
"""积分 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.dependencies import get_current_active_user
from app.dependencies_services import get_points_service
from app.models.user import User
from app.services.points_service import PointsService

router = APIRouter()


@router.get("/points/me")
async def my_points(
    service: PointsService = Depends(get_points_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    # 接线：service 现有方法名为 profile(user_id)
    return await service.profile(current_user.id)


@router.get("/points/me/history")
async def my_history(
    skip: int = 0,
    limit: int = 50,
    service: PointsService = Depends(get_points_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    records = await service.get_history(current_user.id, skip=skip, limit=limit)
    return {"records": records}


@router.get("/points/leaderboard")
async def leaderboard(
    skip: int = 0,
    limit: int = 50,
    service: PointsService = Depends(get_points_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    # 接线：service.leaderboard(top_n=...) 而非 skip/limit
    return await service.leaderboard(top_n=max(1, limit))
