from functools import wraps
from typing import Callable, List, Union

from fastapi import status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PermissionDeniedException, NotFoundException
from app.models.user import User
from app.services.rbac_service import RBACService


class PermissionChecker:
    def __init__(self, required_permissions: Union[str, List[str]], require_all: bool = True):
        """
        权限检查器
        
        Args:
            required_permissions: 需要的权限，可以是单个权限字符串或权限列表
            require_all: 是否需要所有权限，False表示只需要其中一个权限
        """
        if isinstance(required_permissions, str):
            required_permissions = [required_permissions]
        
        self.required_permissions = required_permissions
        self.require_all = require_all
    
    async def __call__(self, user: User, db: AsyncSession) -> bool:
        """
        检查用户是否有权限
        
        Args:
            user: 当前用户
            db: 数据库会话
            
        Returns:
            bool: 是否有权限
        """
        rbac_service = RBACService(db)
        
        # 超级用户拥有所有权限
        if user.is_superuser:
            return True
        
        user_permissions = await rbac_service.get_user_permissions(user.id)
        
        if self.require_all:
            # 需要所有权限
            for permission in self.required_permissions:
                if permission not in user_permissions:
                    return False
            return True
        else:
            # 只需要其中一个权限
            for permission in self.required_permissions:
                if permission in user_permissions:
                    return True
            return False


def require_permission(resource: str, action: str, require_all: bool = True):
    """
    权限检查装饰器
    
    Args:
        resource: 资源名称，如"user", "role"等
        action: 操作名称，如"create", "read", "update", "delete"等
        require_all: 是否需要所有权限
    """
    permission = f"{resource}:{action}"
    checker = PermissionChecker(permission, require_all)
    
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 从kwargs中获取用户和数据库会话
            user = kwargs.get("current_user")
            db = kwargs.get("db")
            
            if not user or not db:
                raise NotFoundException(
                    resource_type="用户或数据库会话",
                    resource_id="missing"
                )
            
            has_permission = await checker(user, db)
            if not has_permission:
                raise PermissionDeniedException(
                    required_permissions=checker.required_permissions
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_superuser(func: Callable):
    """
    超级用户权限检查装饰器
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        user = kwargs.get("current_user")
        
        if not user:
            raise NotFoundException(
                resource_type="用户信息",
                resource_id="missing"
            )
        
        if not user.is_superuser:
            raise PermissionDeniedException(
                required_permissions=["superuser"]
            )
        
        return await func(*args, **kwargs)
    return wrapper


def require_role(role_name: str):
    """
    角色检查装饰器
    
    Args:
        role_name: 需要的角色名称
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user = kwargs.get("current_user")
            db = kwargs.get("db")
            
            if not user or not db:
                raise NotFoundException(
                    resource_type="用户或数据库会话",
                    resource_id="missing"
                )
            
            # 超级用户拥有所有角色权限
            if user.is_superuser:
                return await func(*args, **kwargs)
            
            # 检查用户是否有指定角色
            has_role = False
            for role in user.roles:
                if role.name == role_name:
                    has_role = True
                    break
            
            if not has_role:
                raise PermissionDeniedException(
                    required_permissions=[f"role:{role_name}"]
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator