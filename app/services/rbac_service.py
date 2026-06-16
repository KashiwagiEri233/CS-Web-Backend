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
    
    async def check_permission(self, user_id: int, resource: str, action: str) -> bool:
        """检查用户是否有特定权限"""
        user = await self.rbac_repo.get_user_with_roles(user_id)
        if not user:
            return False

        if user.is_superuser:
            return True

        required_permission = f"{resource}:{action}"
        # 复用已查询的 user 对象，避免重复 DB 查询
        permissions = set()
        for role in user.roles:
            for permission in role.permissions:
                perm_str = f"{permission.resource}:{permission.action}"
                permissions.add(perm_str)

        return required_permission in permissions
    
    async def grant_role_to_user(self, user_id: int, role_id: int) -> bool:
        """为用户授予角色"""
        user = await self.rbac_repo.get_user_by_id(user_id)
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
    
    # 别名方法，与测试用例匹配
    async def assign_role_to_user(self, user_id: int, role_id: int) -> bool:
        """为用户分配角色（alias for grant_role_to_user）"""
        return await self.grant_role_to_user(user_id, role_id)
    
    async def check_user_permission(self, user_id: int, resource: str, action: str) -> bool:
        """检查用户权限（alias for check_permission）"""
        return await self.check_permission(user_id, resource, action)