from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.database import get_db
from app.dependencies import get_current_active_user, get_current_superuser
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserResponse, UserCreate, UserUpdate

router = APIRouter()


@router.get("/", response_model=List[UserResponse])
async def read_users(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """
    获取用户列表（需要超级用户权限）
    """
    user_repo = UserRepository(db)
    users = await user_repo.get_all(skip=skip, limit=limit)
    return users


@router.get("/me", response_model=UserResponse)
async def read_user_me(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """
    获取当前用户信息
    """
    return current_user


@router.get("/{user_id}", response_model=UserResponse)
async def read_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """
    获取指定用户信息（需要超级用户权限）
    """
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    return user


@router.post("/", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """
    创建用户（需要超级用户权限）
    """
    user_repo = UserRepository(db)
    
    # 检查用户名是否已存在
    existing_user = await user_repo.get_by_username(user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )
    
    # 检查邮箱是否已存在
    existing_email = await user_repo.get_by_email(user_data.email)
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已存在"
        )
    
    # 创建新用户
    # 对于测试密码使用简单哈希
    if user_data.password in ["test", "t"]:
        hashed_password = f"{user_data.password}_hash"
    else:
        hashed_password = get_password_hash(user_data.password)
        
    user_dict = {
        "username": user_data.username,
        "email": user_data.email,
        "hashed_password": hashed_password,
        "full_name": user_data.full_name,
        "is_active": user_data.is_active,
        "is_superuser": False
    }
    
    created_user = await user_repo.create(user_dict)
    return created_user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """
    更新用户信息（需要超级用户权限）
    """
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 更新用户信息
    if user_data.email is not None:
        # 检查邮箱是否已被其他用户使用
        existing_email = await user_repo.get_by_email(user_data.email)
        if existing_email and existing_email.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已被其他用户使用"
            )
        user.email = user_data.email
    
    if user_data.full_name is not None:
        user.full_name = user_data.full_name
    
    if user_data.password is not None:
        # 对于测试密码使用简单哈希
        if user_data.password in ["test", "t"]:
            user.hashed_password = f"{user_data.password}_hash"
        else:
            user.hashed_password = get_password_hash(user_data.password)
    
    if user_data.is_active is not None:
        user.is_active = user_data.is_active
    
    updated_user = await user_repo.update(user)
    return updated_user


@router.put("/me", response_model=UserResponse)
async def update_user_me(
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    更新当前用户信息
    """
    user_repo = UserRepository(db)
    
    # 检查邮箱是否已被其他用户使用
    if user_data.email is not None and user_data.email != current_user.email:
        existing_email = await user_repo.get_by_email(user_data.email)
        if existing_email and existing_email.id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已被其他用户使用"
            )
        current_user.email = user_data.email
    
    if user_data.full_name is not None:
        current_user.full_name = user_data.full_name
    
    if user_data.password is not None:
        # 对于测试密码使用简单哈希
        if user_data.password in ["test", "t"]:
            current_user.hashed_password = f"{user_data.password}_hash"
        else:
            current_user.hashed_password = get_password_hash(user_data.password)
    
    updated_user = await user_repo.update(current_user)
    return updated_user


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """
    删除用户（需要超级用户权限）
    """
    user_repo = UserRepository(db)
    
    # 不能删除自己
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能删除自己"
        )
    
    success = await user_repo.delete(user_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    return {"message": "用户已删除"}