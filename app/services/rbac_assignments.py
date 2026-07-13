"""RBAC 用户/角色/权限关联编排。

作为 ``RBACService`` 的职责 mixin，仅承载关联变更；公共入口仍是
``app.services.rbac_service.RBACService``。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.rbac_repo import RBACRepository


class RBACAssignmentMixin:
    """用户角色和角色权限的授予/撤销能力。"""

    db: AsyncSession
    rbac_repo: RBACRepository

    async def _invalidate_user_perm_cache(self, user_id: int) -> None:
        raise NotImplementedError

    async def _invalidate_role_users_perm_cache(self, role_id: int) -> None:
        raise NotImplementedError

    async def user_exists(self, user_id: int) -> bool:
        """判断用户是否存在。"""
        return await self.rbac_repo.get_user_by_id(user_id) is not None

    async def grant_role_to_user(
        self, user_id: int, role_id: int, commit: bool = True
    ) -> bool:
        """为用户授予角色。"""
        user = await self.rbac_repo.get_user_with_roles(user_id)
        role = await self.rbac_repo.get_role_by_id(role_id)
        if not user or not role:
            return False

        if not any(item.id == role.id for item in user.roles):
            user.roles.append(role)
            if commit:
                await self.db.commit()
            await self._invalidate_user_perm_cache(user_id)
        return True

    async def revoke_role_from_user(
        self, user_id: int, role_id: int, commit: bool = True
    ) -> bool:
        """从用户撤销角色。"""
        user = await self.rbac_repo.get_user_with_roles(user_id)
        if not user:
            return False

        role = await self.rbac_repo.get_role_by_id(role_id)
        if not role:
            return False

        target = next((item for item in user.roles if item.id == role.id), None)
        if target is not None:
            user.roles.remove(target)
            if commit:
                await self.db.commit()
            await self._invalidate_user_perm_cache(user_id)
        return True

    async def grant_permission_to_role(
        self, role_id: int, permission_id: int, commit: bool = True
    ) -> bool:
        """为角色授予权限。"""
        role = await self.rbac_repo.get_role_with_permissions(role_id)
        permission = await self.rbac_repo.get_permission_by_id(permission_id)
        if not role or not permission:
            return False

        if permission not in role.permissions:
            role.permissions.append(permission)
            if commit:
                await self.db.commit()
            await self._invalidate_role_users_perm_cache(role_id)
        return True

    async def revoke_permission_from_role(
        self, role_id: int, permission_id: int, commit: bool = True
    ) -> bool:
        """从角色撤销权限。"""
        role = await self.rbac_repo.get_role_with_permissions(role_id)
        if not role:
            return False

        permission = await self.rbac_repo.get_permission_by_id(permission_id)
        if not permission:
            return False

        if permission in role.permissions:
            role.permissions.remove(permission)
            if commit:
                await self.db.commit()
            await self._invalidate_role_users_perm_cache(role_id)
        return True
