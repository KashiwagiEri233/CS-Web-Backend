from typing import List, Optional, Set

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission
from app.repositories.rbac_repo import RBACRepository


class RBACService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.rbac_repo = RBACRepository(db)
    
    async def get_user_permissions(self, user_id: int) -> Set[str]:
        """获取用户所有权限"""
        user = await self.rbac_repo.get_user_with_roles(user_id)
        if not user:
            return set()
        
        permissions = set()
        for role in user.roles:
            for permission in role.permissions:
                # 格式化权限字符串: "resource:action" (例如: "user:create")
                perm_str = f"{permission.resource}:{permission.action}"
                permissions.add(perm_str)
        
        return permissions
    
    async def get_user_roles(self, user_id: int) -> List[Role]:
        """获取用户的角色列表（含角色自身的权限，便于上层展示）。"""
        user = await self.rbac_repo.get_user_with_roles(user_id)
        return list(user.roles) if user else []

    async def check_permission(self, user_id: int, resource: str, action: str) -> bool:
        """检查用户是否有特定权限。

        超级用户拥有全部权限；否则单次加载用户授权后聚合判断，
        避免重复 DB 查询。
        """
        user = await self.rbac_repo.get_user_with_roles(user_id)
        if not user:
            return False
        if user.is_superuser:
            return True

        required = f"{resource}:{action}"
        permissions: Set[str] = set()
        for role in user.roles:
            for permission in role.permissions:
                permissions.add(f"{permission.resource}:{permission.action}")
        return required in permissions

    async def update_role(self, role_id: int, update_data: dict) -> Optional[Role]:
        """更新角色：角色不存在返回 None，否则返回更新后的角色。"""
        role = await self.rbac_repo.get_role_by_id(role_id)
        if not role:
            return None
        return await self.rbac_repo.update_role(role, update_data)

    async def update_permission(self, permission_id: int, update_data: dict) -> Optional[Permission]:
        """更新权限：权限不存在返回 None，否则返回更新后的权限。"""
        permission = await self.rbac_repo.get_permission_by_id(permission_id)
        if not permission:
            return None
        return await self.rbac_repo.update_permission(permission, update_data)
    
    async def grant_role_to_user(self, user_id: int, role_id: int) -> bool:
        """为用户授予角色"""
        # 必须用 get_user_with_roles 预加载 roles，否则下面访问 user.roles
        # 会在异步上下文触发懒加载 -> MissingGreenlet -> 500
        user = await self.rbac_repo.get_user_with_roles(user_id)
        role = await self.rbac_repo.get_role_by_id(role_id)

        if not user or not role:
            return False

        if role not in user.roles:
            user.roles.append(role)
            await self.db.commit()
        
        return True
    
    async def revoke_role_from_user(self, user_id: int, role_id: int) -> bool:
        """从用户撤销角色"""
        user = await self.rbac_repo.get_user_with_roles(user_id)
        
        if not user:
            return False
        
        role = await self.rbac_repo.get_role_by_id(role_id)
        if not role:
            return False
        
        if role in user.roles:
            user.roles.remove(role)
            await self.db.commit()
        
        return True
    
    async def grant_permission_to_role(self, role_id: int, permission_id: int) -> bool:
        """为角色授予权限"""
        role = await self.rbac_repo.get_role_with_permissions(role_id)
        permission = await self.rbac_repo.get_permission_by_id(permission_id)
        
        if not role or not permission:
            return False
        
        if permission not in role.permissions:
            role.permissions.append(permission)
            await self.db.commit()
        
        return True
    
    async def revoke_permission_from_role(self, role_id: int, permission_id: int) -> bool:
        """从角色撤销权限"""
        role = await self.rbac_repo.get_role_with_permissions(role_id)
        
        if not role:
            return False
        
        permission = await self.rbac_repo.get_permission_by_id(permission_id)
        if not permission:
            return False
        
        if permission in role.permissions:
            role.permissions.remove(permission)
            await self.db.commit()

        return True