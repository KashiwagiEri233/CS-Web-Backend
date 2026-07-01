from typing import Optional, List, Tuple

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission


class RBACRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """通过ID获取用户"""
        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_user_with_roles(self, user_id: int) -> Optional[User]:
        """获取用户及其角色（并嵌套预加载角色的权限）。

        嵌套到 roles.permissions 是必要的：权限聚合（get_user_permissions /
        check_permission）会遍历 role.permissions，否则异步下触发懒加载 -> MissingGreenlet。
        """
        stmt = (
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.id == user_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_role_by_id(self, role_id: int) -> Optional[Role]:
        """通过ID获取角色"""
        stmt = select(Role).where(Role.id == role_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_role_by_name(self, role_name: str) -> Optional[Role]:
        """通过名称获取角色"""
        stmt = select(Role).where(Role.name == role_name)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_role_with_permissions(self, role_id: int) -> Optional[Role]:
        """获取角色及其权限"""
        stmt = select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_permission_by_id(self, permission_id: int) -> Optional[Permission]:
        """通过ID获取权限"""
        stmt = select(Permission).where(Permission.id == permission_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_permission_by_name(self, name: str) -> Optional[Permission]:
        """通过名称获取权限"""
        stmt = select(Permission).where(Permission.name == name)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_permission_by_resource_and_action(self, resource: str, action: str) -> Optional[Permission]:
        """通过资源和操作获取权限"""
        stmt = select(Permission).where(
            Permission.resource == resource,
            Permission.action == action
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_all_roles(self, skip: int = 0, limit: Optional[int] = None) -> List[Role]:
        """获取角色列表（含各自权限），可分页。limit=None 表示不分页。"""
        stmt = select(Role).options(selectinload(Role.permissions))
        if limit is not None:
            stmt = stmt.offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_roles(self) -> int:
        """角色总数（用于分页 total）。"""
        result = await self.db.execute(select(func.count()).select_from(Role))
        return int(result.scalar_one())

    async def get_all_permissions(self, skip: int = 0, limit: Optional[int] = None) -> List[Permission]:
        """获取权限列表，可分页。limit=None 表示不分页。"""
        stmt = select(Permission)
        if limit is not None:
            stmt = stmt.offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_permissions(self) -> int:
        """权限总数（用于分页 total）。"""
        result = await self.db.execute(select(func.count()).select_from(Permission))
        return int(result.scalar_one())

    async def get_user_ids_by_role(self, role_id: int) -> List[int]:
        """查询拥有指定角色的全部用户 id（用于权限缓存批量失效）。"""
        from app.models.user import user_roles

        result = await self.db.execute(
            select(user_roles.c.user_id).where(user_roles.c.role_id == role_id)
        )
        return [row[0] for row in result.all()]
    
    async def create_role(self, role_data: dict) -> Role:
        """创建角色"""
        role = Role(**role_data)
        self.db.add(role)
        await self.db.commit()
        await self.db.refresh(role)
        # 预加载权限关系，避免 MissingGreenlet 错误
        # 使用更直接的方式预加载关系
        stmt = select(Role).options(selectinload(Role.permissions)).where(Role.id == role.id)
        result = await self.db.execute(stmt)
        return result.scalar_one()
    
    async def create_permission(self, permission_data: dict) -> Permission:
        """创建权限"""
        permission = Permission(**permission_data)
        self.db.add(permission)
        await self.db.commit()
        await self.db.refresh(permission)
        # 预加载角色关系，避免 MissingGreenlet 错误
        # 使用更直接的方式预加载关系
        stmt = select(Permission).options(selectinload(Permission.roles)).where(Permission.id == permission.id)
        result = await self.db.execute(stmt)
        return result.scalar_one()
    
    async def update_role(self, role: Role, update_data: dict) -> Role:
        """更新角色字段并持久化，返回预加载权限关系后的角色。

        仅写入 update_data 中非 None 的字段；最后重新查询以预加载
        permissions，避免异步懒加载触发 MissingGreenlet。
        """
        for field in ("name", "description", "is_active"):
            value = update_data.get(field)
            if value is not None:
                setattr(role, field, value)

        await self.db.commit()
        stmt = (
            select(Role)
            .options(selectinload(Role.permissions))
            .where(Role.id == role.id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def delete_role(self, role_id: int) -> bool:
        """删除角色"""
        role = await self.get_role_by_id(role_id)
        if not role:
            return False
        
        await self.db.delete(role)
        await self.db.commit()
        return True
    
    async def update_permission(self, permission: Permission, update_data: dict) -> Permission:
        """更新权限字段并持久化，返回预加载角色关系后的权限。

        仅写入 update_data 中非 None 的字段；最后重新查询以预加载
        roles，避免异步懒加载触发 MissingGreenlet。
        """
        for field in ("name", "resource", "action", "description"):
            value = update_data.get(field)
            if value is not None:
                setattr(permission, field, value)

        await self.db.commit()
        stmt = (
            select(Permission)
            .options(selectinload(Permission.roles))
            .where(Permission.id == permission.id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def delete_permission(self, permission_id: int) -> bool:
        """删除权限"""
        permission = await self.get_permission_by_id(permission_id)
        if not permission:
            return False
        
        await self.db.delete(permission)
        await self.db.commit()
        return True
    
    async def assign_permission_to_role(self, role_id: int, permission_id: int) -> bool:
        """为角色分配权限"""
        role = await self.get_role_with_permissions(role_id)
        permission = await self.get_permission_by_id(permission_id)

        if not role or not permission:
            return False

        if permission not in role.permissions:
            role.permissions.append(permission)
            await self.db.commit()

        return True