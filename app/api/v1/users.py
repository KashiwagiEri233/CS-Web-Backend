from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user, get_current_superuser
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, PaginationParams
from app.schemas.user import UserResponse, UserCreate, UserUpdate
from app.services.auth_service import AuthService
from app.services.user_service import UserService

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[UserResponse])
async def read_users(
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """获取用户列表（需要超级用户权限，分页）"""
    user_service = UserService(db)
    users, total = await user_service.list_users(
        skip=pagination.skip, limit=pagination.limit
    )
    return PaginatedResponse(
        items=users, total=total, skip=pagination.skip, limit=pagination.limit
    )


@router.get("/me", response_model=UserResponse)
async def read_user_me(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """获取当前用户信息"""
    return current_user


@router.get("/{user_id}", response_model=UserResponse)
async def read_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """获取指定用户信息（需要超级用户权限）"""
    user_service = UserService(db)
    return await user_service.get_user(user_id)


@router.post("/", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """创建用户（需要超级用户权限）。

    查重 + 哈希 + 落库统一走 AuthService.create_user，
    与 /auth/register 复用同一逻辑。UserCreate 含密码强度/用户名/邮箱验证。
    """
    auth_service = AuthService(db)
    return await auth_service.create_user(user_data, is_superuser=False)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """更新用户信息（需要超级用户权限）"""
    user_service = UserService(db)
    return await user_service.update_user(user_id, user_data.model_dump(exclude_unset=True))


@router.put("/me", response_model=UserResponse)
async def update_user_me(
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """更新当前用户信息（自助资料：不可改 is_active）"""
    user_service = UserService(db)
    return await user_service.update_profile(
        current_user, user_data.model_dump(exclude_unset=True)
    )


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """删除用户（需要超级用户权限）"""
    user_service = UserService(db)
    await user_service.delete_user(user_id, current_user.id)
    return {"message": "用户已删除"}
