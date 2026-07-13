from typing import List, Optional, Set

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.cache import get_cache
from app.core.config import settings
from app.core.loguru_logger import get_logger
from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission
from app.repositories.rbac_repo import RBACRepository

logger = get_logger("rbac")

# 用户权限缓存 TTL（秒）。短 TTL 兼顾热数据加速与变更滞后窗口；
# 真正的即时失效由 grant/revoke 点显式 delete 缓存保证。
_USER_PERM_CACHE_TTL = 60


def _user_perm_cache_key(user_id: int) -> str:
    return f"rbac:user_perms:{user_id}"


async def _invalidate_user_perm_cache(user_id: int) -> None:
    """失效单个用户的权限缓存。缓存故障不抛错。"""
    try:
        await get_cache().delete(_user_perm_cache_key(user_id))
    except Exception:  # noqa: BLE001 - 失效失败不应阻断业务变更
        logger.debug("权限缓存失效失败，忽略", user_id=user_id)


class RBACService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.rbac_repo = RBACRepository(db)
    
    async def get_user_permissions(self, user_id: int) -> Set[str]:
        """获取用户所有权限（带可降级缓存）。

        缓存键 rbac:user_perms:{user_id}，TTL 见 _USER_PERM_CACHE_TTL。
        缓存故障（Redis 不可用等）不抛错，退回直接查库。
        """
        cache = get_cache()
        key = _user_perm_cache_key(user_id)
        try:
            hit = await cache.get(key)
            if hit is not None:
                return set(hit)
        except Exception:  # noqa: BLE001 - 缓存读取绝不应阻断鉴权
            logger.debug("权限缓存读取失败，回退到数据库", user_id=user_id)

        user = await self.rbac_repo.get_user_with_roles(user_id)
        if not user:
            return set()

        permissions: Set[str] = set()
        for role in user.roles:
            for permission in role.permissions:
                # 格式化权限字符串: "resource:action" (例如: "user:create")
                permissions.add(f"{permission.resource}:{permission.action}")

        try:
            await cache.set(key, list(permissions), _USER_PERM_CACHE_TTL)
        except Exception:  # noqa: BLE001
            logger.debug("权限缓存写入失败，忽略", user_id=user_id)

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
        updated = await self.rbac_repo.update_role(role, update_data)
        await self.db.commit()
        # 角色属性变更可能影响授权展示；失效持有该角色的用户权限缓存
        await self._invalidate_role_users_perm_cache(role_id)
        return updated

    async def update_permission(self, permission_id: int, update_data: dict) -> Optional[Permission]:
        """更新权限：权限不存在返回 None，否则返回更新后的权限。"""
        permission = await self.rbac_repo.get_permission_by_id(permission_id)
        if not permission:
            return None
        # 变更前取关联角色，用于缓存失效
        role_ids = await self.rbac_repo.get_role_ids_by_permission(permission_id)
        updated = await self.rbac_repo.update_permission(permission, update_data)
        await self.db.commit()
        for rid in role_ids:
            await self._invalidate_role_users_perm_cache(rid)
        return updated

    # ------------------------------------------------------------------ 角色 / 权限 CRUD
    # 路由层统一通过这些方法访问数据，避免直接操作 repo。

    async def get_all_roles(self, skip: int = 0, limit: Optional[int] = None) -> List[Role]:
        """获取角色列表（含各自权限），可分页。"""
        return await self.rbac_repo.get_all_roles(skip=skip, limit=limit)

    async def count_roles(self) -> int:
        """角色总数（用于分页 total）。"""
        return await self.rbac_repo.count_roles()

    async def get_role(self, role_id: int) -> Optional[Role]:
        """获取指定角色（含权限）。"""
        return await self.rbac_repo.get_role_with_permissions(role_id)

    async def create_role(self, role_data: dict) -> Role:
        """创建角色。调用方应先做名称查重。"""
        role = await self.rbac_repo.create_role(role_data)
        await self.db.commit()
        return role

    async def delete_role(self, role_id: int) -> bool:
        """删除角色：角色不存在返回 False。"""
        # 删除前先收集受影响用户，便于提交后清缓存
        user_ids = await self.rbac_repo.get_user_ids_by_role(role_id)
        ok = await self.rbac_repo.delete_role(role_id)
        if ok:
            await self.db.commit()
            for uid in user_ids:
                await _invalidate_user_perm_cache(uid)
        return ok

    async def get_all_permissions(self, skip: int = 0, limit: Optional[int] = None) -> List[Permission]:
        """获取权限列表，可分页。"""
        return await self.rbac_repo.get_all_permissions(skip=skip, limit=limit)

    async def count_permissions(self) -> int:
        """权限总数（用于分页 total）。"""
        return await self.rbac_repo.count_permissions()

    async def get_permission(self, permission_id: int) -> Optional[Permission]:
        """获取指定权限。"""
        return await self.rbac_repo.get_permission_by_id(permission_id)

    async def create_permission(self, permission_data: dict) -> Permission:
        """创建权限。调用方应先做名称查重。"""
        permission = await self.rbac_repo.create_permission(permission_data)
        await self.db.commit()
        return permission

    async def delete_permission(self, permission_id: int) -> bool:
        """删除权限：权限不存在返回 False。"""
        role_ids = await self.rbac_repo.get_role_ids_by_permission(permission_id)
        ok = await self.rbac_repo.delete_permission(permission_id)
        if ok:
            await self.db.commit()
            for rid in role_ids:
                await self._invalidate_role_users_perm_cache(rid)
        return ok

    async def get_role_by_name(self, name: str) -> Optional[Role]:
        """按名称查角色（用于查重）。"""
        return await self.rbac_repo.get_role_by_name(name)

    async def get_permission_by_name(self, name: str) -> Optional[Permission]:
        """按名称查权限（用于查重）。"""
        return await self.rbac_repo.get_permission_by_name(name)

    async def get_permission_by_resource_action(self, resource: str, action: str) -> Optional[Permission]:
        """按 resource+action 查权限（用于查重，与唯一约束对齐）。"""
        return await self.rbac_repo.get_permission_by_resource_and_action(resource, action)

    async def user_exists(self, user_id: int) -> bool:
        """判断用户是否存在（供路由层做存在性校验，避免穿透到 repo）。"""
        return await self.rbac_repo.get_user_by_id(user_id) is not None
    
    async def grant_role_to_user(self, user_id: int, role_id: int) -> bool:
        """为用户授予角色"""
        # 必须用 get_user_with_roles 预加载 roles，否则下面访问 user.roles
        # 会在异步上下文触发懒加载 -> MissingGreenlet -> 500
        user = await self.rbac_repo.get_user_with_roles(user_id)
        role = await self.rbac_repo.get_role_by_id(role_id)

        if not user or not role:
            return False

        if not any(r.id == role.id for r in user.roles):
            user.roles.append(role)
            await self.db.commit()
            await _invalidate_user_perm_cache(user_id)

        return True

    async def revoke_role_from_user(self, user_id: int, role_id: int) -> bool:
        """从用户撤销角色"""
        user = await self.rbac_repo.get_user_with_roles(user_id)

        if not user:
            return False

        role = await self.rbac_repo.get_role_by_id(role_id)
        if not role:
            return False

        # 按已加载集合遍历一次，定位到目标角色后移除（避免重复 __eq__）
        target = next((r for r in user.roles if r.id == role.id), None)
        if target is not None:
            user.roles.remove(target)
            await self.db.commit()
            await _invalidate_user_perm_cache(user_id)

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
            await self._invalidate_role_users_perm_cache(role_id)

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
            await self._invalidate_role_users_perm_cache(role_id)

        return True

    # ------------------------------------------------------------------ 权限缓存失效

    async def _invalidate_role_users_perm_cache(self, role_id: int) -> None:
        """失效指定角色下所有用户的权限缓存（role↔permission 变更时调用）。"""
        user_ids = await self.rbac_repo.get_user_ids_by_role(role_id)
        for uid in user_ids:
            await _invalidate_user_perm_cache(uid)