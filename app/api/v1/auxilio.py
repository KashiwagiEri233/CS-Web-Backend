"""学习助手 API：AI 答疑 + 学习路径 + 资源推荐。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends

from app.dependencies import get_current_active_user
from app.dependencies_services import get_auxilio_service
from app.models.user import User
from app.services.auxilio_service import AuxilioService

router = APIRouter()


@router.post("/auxilio/chat")
async def auxilio_chat(
    message: str,
    context: Optional[str] = None,
    service: AuxilioService = Depends(get_auxilio_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return await service.chat(current_user.id, message, context)


@router.post("/auxilio/path")
async def auxilio_path(
    goal: str,
    service: AuxilioService = Depends(get_auxilio_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return await service.generate_path(current_user.id, goal)


@router.get("/auxilio/recommend")
async def auxilio_recommend(
    service: AuxilioService = Depends(get_auxilio_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return await service.recommend_resources(current_user.id)
