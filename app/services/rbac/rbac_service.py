from typing import Iterable, List, Optional, Sequence, Set


from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_cache
from app.core.exceptions import (
    AuthorizationException,
    BaseAppException,
    ConflictException,
    ErrorCode,
    NotFoundException,
    ValidationException,
)
from app.core.loguru_logger import get_logger
from app.models.role import Role
from app.models.permission import Permission
from app.models.user import User
from app.repositories.rbac_repo import RBACRepository
from app.schemas.rbac import AdminRoleCreate, AdminRoleUpdate
from app.core.constants import RBAC_USER_PERMISSION_CACHE_TTL_SECONDS
from app.services.rbac.rbac_assignments import RBACAssignmentMixin
from app.services.rbac.rbac_seed_data import (
    CUSTOM_ROLE_SCOPE_POLICY,
    NON_DELEGABLE_PERMISSIONS,
    PROTECTED_ROLE_NAMES,
    ROLE_SCOPE_POLICY,
)

logger = get_logger("rbac")

# 用户权限缓存 TTL（秒）。短 TTL 兼顾热数据加速与变更滞后窗口；
# 真正的即时失效由 grant/revoke 点显式 delete 缓存保证。
# 具体值见 app.core.constants.RBAC_USER_PERMISSION_CACHE_TTL_SECONDS。


def _user_perm_cache_key(user_id: int, version: int) -> str:
    """权限缓存键含授权版本：版本递增后旧键不可达，撤权立即生效。"""
    return f"rbac:user_perms:{user_id}:v{version}"


async def _invalidate_user_perm_cache(
    user_id: int, version: int, raise_on_failure: bool = False
) -> None:
    """失效单个用户某一版本的权限缓存。"""
    try:
        await get_cache().delete(_user_perm_cache_key(user_id, version))
    except Exception as exc:  # noqa: BLE001
        logger.warning("权限缓存失效失败（单用户）", user_id=user_id, error=str(exc))
        if raise_on_failure:
            raise RuntimeError(
                f"权限缓存失效失败，已中止本次授权变更以避免撤权后残留权限：{exc}"
            ) from exc


async def _invalidate_user_perm_cache_many(
    entries: Iterable[tuple[int, int]], raise_on_failure: bool = False
) -> None:
    """批量失效多个用户各自版本的权限缓存（整批一次往返）。"""
    keys = [_user_perm_cache_key(uid, ver) for uid, ver in entries]
    if not keys:
        return
    try:
        await get_cache().delete_many(keys)
    except Exception as exc:  # noqa: BLE001
        logger.warning("权限缓存批量失效失败", count=len(keys), error=str(exc))
        if raise_on_failure:
            raise RuntimeError(
                f"权限缓存批量失效失败，已中止本次授权变更以避免撤权后残留权限：{exc}"
            ) from exc


class RBACService(RBACAssignmentMixin):
    def __init__(self, db: AsyncSession):
        self.db = db
        self.rbac_repo = RBACRepository(db)

    async def get_user_permissions(
        self, user_id: int, authorization_version: Optional[int] = None
    ) -> Set[str]:
        """获取用户所有权限（带版本化可降级缓存）。**鉴权与展示共用此入口。**

        authorization_version 由已加载的当前用户传入（鉴权中间件），避免每请求
        额外查版本；未传入时（后台脚本/其他用户查询）回源读取一次。
        """
        if authorization_version is None:
            authorization_version = (
                await self.rbac_repo.get_user_authorization_version(user_id) or 0
            )
        cache = get_cache()
        key = _user_perm_cache_key(user_id, authorization_version)
        try:
            hit = await cache.get(key)
            if hit is not None:
                return set(hit)
        except Exception:  # noqa: BLE001 - 缓存读取绝不应阻断鉴权
            logger.debug("权限缓存读取失败，回退到数据库", user_id=user_id)

        # 未命中走平铺 join：一次查询直接取回权限串集合。
        # 对比 get_user_with_roles + 内存聚合的三次往返（user / roles / permissions）
        # 且要实例化整棵关系树——这里只需要一组字符串。
        # 两者语义等价（软删用户与未启用角色都不计入），已由集成测试锁死。
        permissions = await self.rbac_repo.get_authorization_permissions(user_id)

        try:
            await cache.set(
                key, list(permissions), RBAC_USER_PERMISSION_CACHE_TTL_SECONDS
            )
        except Exception:  # noqa: BLE001
            logger.debug("权限缓存写入失败，忽略", user_id=user_id)

        return permissions

    async def get_user_roles(self, user_id: int) -> List[Role]:
        """获取用户的角色列表（含角色自身的权限，便于上层展示）。"""
        user = await self.rbac_repo.get_user_with_roles(user_id)
        return list(user.roles) if user else []

    async def get_authorization_permissions(self, user_id: int) -> Set[str]:
        """一次查询取回用户的全部有效权限串（不经缓存）。

        ``get_user_permissions`` 缓存未命中时的底层实现；也可单独用于需要
        绕过缓存、确保读到最新授权的场景。
        """
        return await self.rbac_repo.get_authorization_permissions(user_id)

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
            if not role.is_active:
                continue
            for permission in role.permissions:
                permissions.add(f"{permission.resource}:{permission.action}")
        return required in permissions

    async def update_role(
        self, role_id: int, update_data: dict, commit: bool = True
    ) -> Optional[Role]:
        """更新角色：角色不存在返回 None，否则返回更新后的角色。"""
        role = await self.rbac_repo.get_role_by_id(role_id)
        if not role:
            return None
        new_name = update_data.get("name")
        if new_name:
            existing = await self.rbac_repo.get_role_by_name(new_name)
            if existing is not None and existing.id != role_id:
                raise ConflictException(message="角色名称已存在")
        try:
            updated = await self.rbac_repo.update_role(role, update_data)
            if commit:
                await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictException(message="角色数据与现有记录冲突") from exc
        # 角色属性变更可能影响授权展示；失效持有该角色的用户权限缓存
        await self._invalidate_role_users_perm_cache(role_id)
        return updated

    async def update_permission(
        self, permission_id: int, update_data: dict, commit: bool = True
    ) -> Optional[Permission]:
        """更新权限：权限不存在返回 None，否则返回更新后的权限。"""
        permission = await self.rbac_repo.get_permission_by_id(permission_id)
        if not permission:
            return None
        name = update_data.get("name", permission.name)
        resource = update_data.get("resource", permission.resource)
        action = update_data.get("action", permission.action)
        by_name = await self.rbac_repo.get_permission_by_name(name)
        by_key = await self.rbac_repo.get_permission_by_resource_and_action(
            resource, action
        )
        if (by_name is not None and by_name.id != permission_id) or (
            by_key is not None and by_key.id != permission_id
        ):
            raise ConflictException(message="权限名称或资源操作已存在")

        # 变更前取关联角色，用于缓存失效
        role_ids = await self.rbac_repo.get_role_ids_by_permission(permission_id)
        # 高危：权限定义变更可能改变授权语义（等同撤权），提交前失效缓存（fail-closed）
        await self._invalidate_roles_users_perm_cache(role_ids, raise_on_failure=True)
        try:
            updated = await self.rbac_repo.update_permission(permission, update_data)
            if commit:
                await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictException(message="权限数据与现有记录冲突") from exc
        return updated

    # ------------------------------------------------------------------ 角色 / 权限 CRUD
    # 路由层统一通过这些方法访问数据，避免直接操作 repo。

    async def get_all_roles(
        self, skip: int = 0, limit: Optional[int] = None
    ) -> List[Role]:
        """获取角色列表（含各自权限），可分页。"""
        return await self.rbac_repo.get_all_roles(skip=skip, limit=limit)

    async def count_roles(self) -> int:
        """角色总数（用于分页 total）。"""
        return await self.rbac_repo.count_roles()

    async def get_role(self, role_id: int) -> Optional[Role]:
        """获取指定角色（含权限）。"""
        return await self.rbac_repo.get_role_with_permissions(role_id)

    async def create_role(self, role_data: dict, commit: bool = True) -> Role:
        """创建角色。调用方应先做名称查重。"""
        try:
            role = await self.rbac_repo.create_role(role_data)
            if commit:
                await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictException(message="角色名称已存在") from exc
        return role

    async def delete_role(self, role_id: int, commit: bool = True) -> bool:
        """删除角色：角色不存在返回 False。"""
        # 删除前先收集受影响用户，提交前清缓存（高危撤权，fail-closed）
        user_ids = await self.rbac_repo.get_user_ids_by_role(role_id)
        await _invalidate_user_perm_cache_many(user_ids, raise_on_failure=True)
        ok = await self.rbac_repo.delete_role(role_id)
        if ok and commit:
            await self.db.commit()
        return ok

    async def get_all_permissions(
        self, skip: int = 0, limit: Optional[int] = None
    ) -> List[Permission]:
        """获取权限列表，可分页。"""
        return await self.rbac_repo.get_all_permissions(skip=skip, limit=limit)

    async def count_permissions(self) -> int:
        """权限总数（用于分页 total）。"""
        return await self.rbac_repo.count_permissions()

    async def get_permission(self, permission_id: int) -> Optional[Permission]:
        """获取指定权限。"""
        return await self.rbac_repo.get_permission_by_id(permission_id)

    async def create_permission(
        self, permission_data: dict, commit: bool = True
    ) -> Permission:
        """创建权限。调用方应先做名称查重。"""
        try:
            permission = await self.rbac_repo.create_permission(permission_data)
            if commit:
                await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictException(message="权限名称或资源操作已存在") from exc
        return permission

    async def delete_permission(self, permission_id: int, commit: bool = True) -> bool:
        """删除权限：权限不存在返回 False。"""
        role_ids = await self.rbac_repo.get_role_ids_by_permission(permission_id)
        # 高危撤权：提交前失效缓存，失败则中止（fail-closed）
        await self._invalidate_roles_users_perm_cache(role_ids, raise_on_failure=True)
        ok = await self.rbac_repo.delete_permission(permission_id)
        if ok and commit:
            await self.db.commit()
        return ok

    async def get_role_by_name(self, name: str) -> Optional[Role]:
        """按名称查角色（用于查重）。"""
        return await self.rbac_repo.get_role_by_name(name)

    async def get_permission_by_name(self, name: str) -> Optional[Permission]:
        """按名称查权限（用于查重）。"""
        return await self.rbac_repo.get_permission_by_name(name)

    async def get_permission_by_resource_action(
        self, resource: str, action: str
    ) -> Optional[Permission]:
        """按 resource+action 查权限（用于查重，与唯一约束对齐）。"""
        return await self.rbac_repo.get_permission_by_resource_and_action(
            resource, action
        )

    # ------------------------------------------------------------------ 管理员视图

    async def list_roles_admin(self) -> list[dict]:
        """管理员角色列表：角色 + 权限名 + 用户数（对齐前端 admin 角色管理 UI）。"""
        roles = await self.rbac_repo.get_all_roles(limit=None)
        result: list[dict] = []
        for role in roles:
            user_count = len(await self.rbac_repo.get_user_ids_by_role(role.id))
            result.append(
                {
                    "id": role.id,
                    "name": role.name,
                    "display_name": role.display_name or role.name,
                    "fantasy_display_name": role.fantasy_display_name,
                    "description": role.description,
                    "is_system": role.is_system,
                    "is_protected": role.is_system
                    or role.name in PROTECTED_ROLE_NAMES,
                    "sort_order": role.sort_order,
                    "permissions": [p.name for p in role.permissions],
                    "audit_domains": list(role.audit_domains or []),
                    "user_count": user_count,
                    "created_at": role.created_at,
                    "updated_at": role.updated_at,
                }
            )
        return result

    async def create_role_admin(
        self, data: "AdminRoleCreate", commit: bool = True
    ) -> Role:
        """管理员创建角色：建角色 + 确保权限存在 + 批量授予（同一事务）。"""
        if await self.rbac_repo.get_role_by_name(data.name):
            raise ConflictException(
                message="角色 key 已存在", details={"name": data.name}
            )
        role = await self.rbac_repo.create_role(
            {
                "name": data.name,
                "display_name": data.display_name,
                "fantasy_display_name": data.fantasy_display_name,
                "description": data.description,
                "audit_domains": data.audit_domains,
                "is_system": False,
                "is_active": True,
            }
        )
        await self._grant_permission_names(role.id, data.permissions)
        if commit:
            await self.db.commit()
        return role

    async def update_role_admin(
        self, role_id: int, data: "AdminRoleUpdate", commit: bool = True
    ) -> Optional[Role]:
        """管理员更新角色元数据（display_name/description）。"""
        role = await self.rbac_repo.get_role_by_id(role_id)
        if not role:
            return None
        await self.rbac_repo.update_role(
            role,
            {
                "display_name": data.display_name,
                "fantasy_display_name": data.fantasy_display_name,
                "description": data.description,
                "audit_domains": data.audit_domains,
            },
        )
        if commit:
            await self.db.commit()
        return role

    async def delete_role_admin(self, role_id: int, commit: bool = True) -> bool:
        """管理员删除角色：系统内置角色（is_system）禁止删除。"""
        role = await self.rbac_repo.get_role_by_id(role_id)
        if not role:
            return False
        if role.is_system:
            raise ConflictException(
                message="系统内置角色不可删除",
                details={"role": role.name},
            )
        # 高危撤权：提交前失效缓存，失败则中止（fail-closed）
        await self._invalidate_role_users_perm_cache(role_id, raise_on_failure=True)
        ok = await self.rbac_repo.delete_role(role_id)
        if ok and commit:
            await self.db.commit()
        return ok

    async def replace_role_permissions(
        self, role_id: int, permission_names: list[str], commit: bool = True
    ) -> Optional[Role]:
        """全量替换角色权限：只接受代码权限目录中已存在的权限名。

        统一后禁止运行时自动创建权限（否则可借未知权限串扩大目录）；
        未注册的权限名返回 422 UNKNOWN_PERMISSION。
        """
        role = await self.rbac_repo.get_role_by_id(role_id)
        if not role:
            return None
        permission_ids: list[int] = []
        unknown: list[str] = []
        for name in permission_names:
            permission = await self.rbac_repo.get_permission_by_name(name)
            if permission is None:
                unknown.append(name)
                continue
            permission_ids.append(permission.id)
        if unknown:
            raise ValidationException(
                message="包含未注册权限，禁止自动创建",
                error_code=ErrorCode.Validation.UNKNOWN_PERMISSION,
                details={"unknown_permissions": unknown},
            )
        # 高危：全量替换可能移除权限（撤权），提交前失效缓存（fail-closed）
        await self._invalidate_role_users_perm_cache(role_id, raise_on_failure=True)
        await self.rbac_repo.replace_role_permissions(role_id, permission_ids)
        if commit:
            await self.db.commit()
        return role

    async def list_permissions_admin(self) -> list[Permission]:
        """管理员权限点列表（全部，不分页）。"""
        return await self.rbac_repo.get_all_permissions(limit=None)

    async def _grant_permission_names(self, role_id: int, names: list[str]) -> None:
        """建角色时的权限授予（复用 replace 语义，未 commit）。"""
        await self.replace_role_permissions(role_id, names, commit=False)

    # ------------------------------------------------------------------ 角色绑定（带作用范围）

    async def get_user_bindings(self, user_id: int) -> list[dict]:
        """返回用户的角色绑定（角色标识 + 双展示名 + scope）。"""
        return await self.rbac_repo.get_user_bindings(user_id)

    async def get_user_authorization_version(self, user_id: int) -> Optional[int]:
        """读取用户授权版本；用户不存在返回 None。"""
        return await self.rbac_repo.get_user_authorization_version(user_id)

    async def replace_user_role_bindings(
        self,
        user_id: int,
        bindings: Sequence[dict],
        actor: User,
        expected_version: Optional[int],
        commit: bool = True,
    ) -> list[dict]:
        """整组替换用户角色绑定。

        防提权规则：
        - 受保护角色（admin/rbac_admin）与超级用户目标的绑定只允许超级用户操作；
        - 非超级用户不得授予含安全管理权限的自定义角色；
        - 绑定 scope 必须符合角色策略（member=own，peak_manager=peak 等）；
        - 非超级用户不能授予 all 范围的自定义角色绑定。
        """
        current_version = await self.rbac_repo.get_user_authorization_version(user_id)
        if current_version is None:
            raise NotFoundException(
                message="用户不存在", resource_type="user", resource_id=user_id
            )
        if expected_version is None:
            raise BaseAppException(
                message="缺少 If-Match 授权版本",
                error_code=ErrorCode.Conflict.VERSION_REQUIRED,
                status_code=428,
            )
        if expected_version != current_version:
            raise BaseAppException(
                message="授权版本已变化，请刷新后重试",
                error_code=ErrorCode.Conflict.VERSION_MISMATCH,
                status_code=412,
                details={"current_version": current_version},
            )

        target = await self.rbac_repo.get_user_with_roles(user_id)
        if target is None:
            raise NotFoundException(
                message="用户不存在", resource_type="user", resource_id=user_id
            )

        validated: list[dict] = []
        seen: set[tuple] = set()
        for item in bindings:
            role = await self.rbac_repo.get_role_by_id(item["role_id"])
            if role is None:
                raise NotFoundException(
                    message="角色不存在",
                    resource_type="role",
                    resource_id=item["role_id"],
                )
            if role.name in PROTECTED_ROLE_NAMES or target.is_superuser:
                if not actor.is_superuser:
                    raise AuthorizationException(
                        message="只有超级用户可以分配受保护角色或修改超级用户授权",
                        error_code=ErrorCode.Authorization.ROLE_ASSIGNMENT_FORBIDDEN,
                        details={"required_permissions": ["superuser"]},
                    )

            if role.name in ROLE_SCOPE_POLICY:
                allowed_scopes = ROLE_SCOPE_POLICY[role.name]
            else:
                allowed_scopes = CUSTOM_ROLE_SCOPE_POLICY
                if not actor.is_superuser:
                    permissions = await self.rbac_repo.get_role_permissions_names(
                        role.id
                    )
                    if permissions & NON_DELEGABLE_PERMISSIONS:
                        raise AuthorizationException(
                            message="该角色的安全管理权限不可委托",
                            error_code=ErrorCode.Authorization.ROLE_ASSIGNMENT_FORBIDDEN,
                            details={"required_permissions": ["superuser"]},
                        )

            if item["scope_type"] not in allowed_scopes:
                raise AuthorizationException(
                    message="该角色不允许此作用范围",
                    error_code=ErrorCode.Authorization.SCOPE_FORBIDDEN,
                    details={
                        "role": role.name,
                        "scope_type": item["scope_type"],
                        "allowed": sorted(allowed_scopes),
                    },
                )

            peak_id = item.get("scope_peak_id")
            if item["scope_type"] == "peak":
                if not peak_id:
                    raise AuthorizationException(
                        message="peak 范围必须指定峰",
                        error_code=ErrorCode.Authorization.SCOPE_FORBIDDEN,
                    )
                peak = await self.rbac_repo.get_peak_by_id(peak_id)
                if peak is None or not peak.is_active or peak.archived_at is not None:
                    raise AuthorizationException(
                        message="峰不存在或不可用",
                        error_code=ErrorCode.Authorization.SCOPE_FORBIDDEN,
                        details={"peak_id": peak_id},
                    )
            elif peak_id:
                raise AuthorizationException(
                    message="只有 peak 范围允许指定峰",
                    error_code=ErrorCode.Authorization.SCOPE_FORBIDDEN,
                )

            key = (role.id, item["scope_type"], peak_id)
            if key in seen:
                continue
            seen.add(key)
            validated.append(
                {
                    "role_id": role.id,
                    "scope_type": item["scope_type"],
                    "scope_peak_id": peak_id,
                }
            )

        await self._invalidate_user_perm_cache(user_id, raise_on_failure=True)
        await self.rbac_repo.replace_user_bindings(
            user_id, validated, created_by=actor.id
        )
        if commit:
            await self.db.commit()
        return await self.rbac_repo.get_user_bindings(user_id)

    # ------------------------------------------------------------------ 权限缓存失效

    async def _invalidate_user_perm_cache(
        self, user_id: int, raise_on_failure: bool = False
    ) -> None:
        version = await self.rbac_repo.get_user_authorization_version(user_id) or 0
        await _invalidate_user_perm_cache(
            user_id, version, raise_on_failure=raise_on_failure
        )

    async def _invalidate_role_users_perm_cache(
        self, role_id: int, raise_on_failure: bool = False
    ) -> None:
        """失效指定角色下所有用户各自版本的权限缓存（role↔permission 变更时调用）。"""
        user_ids = await self.rbac_repo.get_user_ids_by_role(role_id)
        versions = await self.rbac_repo.get_authorization_versions(user_ids)
        await _invalidate_user_perm_cache_many(
            [(uid, versions.get(uid, 0)) for uid in user_ids],
            raise_on_failure=raise_on_failure,
        )

    async def _invalidate_roles_users_perm_cache(
        self, role_ids: Sequence[int], raise_on_failure: bool = False
    ) -> None:
        """失效这批角色下所有用户各自版本的权限缓存（权限定义变更时调用）。

        一次 IN 查询取回受影响用户 + 一次批量删除，不随角色数线性增长往返次数。
        """
        user_ids = await self.rbac_repo.get_user_ids_by_roles(role_ids)
        versions = await self.rbac_repo.get_authorization_versions(user_ids)
        await _invalidate_user_perm_cache_many(
            [(uid, versions.get(uid, 0)) for uid in user_ids],
            raise_on_failure=raise_on_failure,
        )
