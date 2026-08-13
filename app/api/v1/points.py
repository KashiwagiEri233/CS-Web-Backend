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
    return await service.get_user_points(current_user.id)


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
    return await service.leaderboard(skip=skip, limit=limit)
