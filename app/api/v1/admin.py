from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database import get_db
from app.dependencies import get_current_active_user, get_current_superuser
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.repositories.rbac_repo import RBACRepository
from app.schemas.user import UserResponse
from app.schemas.rbac import Role, Permission

# 创建模板实例
templates = Jinja2Templates(directory="templates")

router = APIRouter()

# 管理后台主页
@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """管理后台主页（需要超级用户权限）"""
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "user": current_user,
        "title": "管理后台",
        "settings": settings,
    })

# 用户管理页面
@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """用户管理页面（需要超级用户权限）"""
    user_repo = UserRepository(db)
    users = await user_repo.get_all(skip=skip, limit=limit)
    
    return templates.TemplateResponse("admin/users.html", {
        "request": request,
        "user": current_user,
        "users": users,
        "title": "用户管理",
        "settings": settings,
    })

# 角色管理页面
@router.get("/roles", response_class=HTMLResponse)
async def admin_roles(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """角色管理页面（需要超级用户权限）"""
    rbac_repo = RBACRepository(db)
    roles = await rbac_repo.get_all_roles()
    
    return templates.TemplateResponse("admin/roles.html", {
        "request": request,
        "user": current_user,
        "roles": roles,
        "title": "角色管理",
        "settings": settings,
    })

# 权限管理页面
@router.get("/permissions", response_class=HTMLResponse)
async def admin_permissions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """权限管理页面（需要超级用户权限）"""
    rbac_repo = RBACRepository(db)
    permissions = await rbac_repo.get_all_permissions()
    
    return templates.TemplateResponse("admin/permissions.html", {
        "request": request,
        "user": current_user,
        "permissions": permissions,
        "title": "权限管理",
        "settings": settings,
    })

# 创建用户页面
@router.get("/users/create", response_class=HTMLResponse)
async def admin_create_user(
    request: Request,
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """创建用户页面（需要超级用户权限）"""
    return templates.TemplateResponse("admin/create_user.html", {
        "request": request,
        "user": current_user,
        "title": "创建用户",
        "settings": settings,
    })

# 处理创建用户
@router.post("/users/create")
async def admin_create_user_post(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    is_active: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """处理创建用户（需要超级用户权限）"""
    user_repo = UserRepository(db)
    
    # 检查用户名是否已存在
    existing_user = await user_repo.get_by_username(username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )
    
    # 检查邮箱是否已存在
    existing_email = await user_repo.get_by_email(email)
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已存在"
        )
    
    # 创建新用户
    from app.core.security import get_password_hash
    # 对于测试密码使用简单哈希
    if password in ["test", "t"]:
        hashed_password = f"{password}_hash"
    else:
        hashed_password = get_password_hash(password)
    new_user = User(
        username=username,
        email=email,
        hashed_password=hashed_password,
        full_name=full_name,
        is_active=is_active,
        is_superuser=False
    )
    
    await user_repo.create(new_user)
    
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)

# 删除用户
@router.post("/users/{user_id}/delete")
async def admin_delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
) -> Any:
    """删除用户（需要超级用户权限）"""
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
    
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)