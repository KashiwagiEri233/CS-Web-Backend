"""用户管理服务（管理员操作）：列表/编辑/启停/重置密码/硬删除。

C-17 拆分第二切片：从 user_service.py 抽出。admin 域与自我 CRUD、
个人资料域零内部方法交叉；仅通过组合 UserService 委托 get_user
（admin_users 路由的管理员详情页与 users 路由共用）。

事务约定：所有写操作的审计走 _audit_admin 的 record_atomic 同事务
原子提交（管理员审计不丢，门槛#2），审计失败整体回滚。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ErrorCode,
    NotFoundException,
)
from app.core.security import async_get_password_hash
from app.core.timezone import now_utc
from app.models.user import User
from app.repositories.login_history_repo import LoginHistoryRepository
from app.repositories.password_history_repo import PasswordHistoryRepository
from app.repositories.rbac_repo import RBACRepository
from app.repositories.refresh_token_repo import RefreshTokenRepository
from app.repositories.user_repo import UserRepository
from app.schemas.auth import UserOut
from app.schemas.pagination import compute_total_pages
from app.schemas.user import AdminUserUpdate
from app.services.audit_service import AuditService
from app.services.user.user_service import UserService


def to_admin_out(user: User) -> dict:
    """UserOut + roles（前端管理员视图需要角色列表；admin_users 路由与 user_service 共用，波次 B2 收敛）。"""
    base = UserOut.model_validate(user).model_dump()
    base["roles"] = [r.name for r in user.roles]
    return base


class UserAdminService:
    """用户管理服务（管理员操作）。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.refresh_repo = RefreshTokenRepository(db)
        self.login_history_repo = LoginHistoryRepository(db)
        self.password_history_repo = PasswordHistoryRepository(db)
        self.rbac_repo = RBACRepository(db)
        # 注入共享请求会话，使 record_atomic 可同事务提交审计（否则 db=None 会抛错）；与 auth_service 一致
        self.audit = AuditService(self.db)
        # 组合 UserService 委托 get_user（含 NotFound 语义），避免复制查询逻辑
        self.user_service = UserService(db)

    async def get_user(self, user_id: int) -> User:
        """用户详情（管理员视角）：委托 UserService.get_user（含 NotFound）。"""
        return await self.user_service.get_user(user_id)

    async def list_users_admin(
        self,
        *,
        search: Optional[str] = None,
        role: str = "all",
        active: str = "all",
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """管理员用户列表：search 匹配 email/display_name；role/active 筛选；分页。"""
        page = max(1, page)
        page_size = min(max(1, page_size), 200)

        users, total = await self.user_repo.list_admin_paginated(
            search=search,
            role=role,
            active=active,
            skip=(page - 1) * page_size,
            limit=page_size,
        )

        return {
            "users": [to_admin_out(u) for u in users],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": compute_total_pages(total, page_size),
        }

    async def update_user_admin(
        self,
        actor: User,
        target_user_id: int,
        update: AdminUserUpdate,
        client_meta: Optional[dict] = None,
    ) -> User:
        """管理员编辑用户：超级用户可改角色/is_active；普通管理员仅资料字段。

        ROOT_PROTECTED：目标为超级用户不可修改。
        SELF_DEMOTE：不能修改自己的角色。
        LAST_ADMIN：不能降级最后一个活跃管理员。
        """
        target = await self.user_repo.get_user_with_roles(target_user_id)
        if target is None or target.deleted_at is not None:
            raise NotFoundException(
                message="用户不存在",
                resource_type="user",
                resource_id=str(target_user_id),
            )
        if target.is_superuser:
            raise AuthorizationException(
                message="超级管理员账号不可被修改",
                error_code=ErrorCode.Authorization.ROOT_PROTECTED,
            )

        data = update.model_dump(exclude_unset=True)
        role_change = data.pop("role", None)
        active_change = data.pop("is_active", None)

        # 资料字段（普通管理员也允许）
        if data:
            user_roles = await self._admin_role_names(actor)
            can_edit_profile = actor.is_superuser or "admin" in user_roles
            if not can_edit_profile:
                raise AuthorizationException(
                    message="权限不足",
                    error_code=ErrorCode.Authorization.PERMISSION_DENIED,
                )
            for key, value in data.items():
                setattr(target, key, value)

        # 角色变更（仅超级用户）
        if role_change is not None:
            if not actor.is_superuser:
                raise AuthorizationException(
                    message="仅超级管理员可修改角色",
                    error_code=ErrorCode.Authorization.PERMISSION_DENIED,
                )
            if actor.id == target.id:
                raise AuthorizationException(
                    message="不能修改自己的角色",
                    error_code=ErrorCode.Authorization.SELF_DEMOTE,
                )
            if self._is_admin_target(target) and role_change != "admin":
                if await self._active_admin_count() <= 1:
                    raise ConflictException(
                        message="不能降级最后一个管理员，请先提升其他用户为管理员",
                        error_code=ErrorCode.Authorization.LAST_ADMIN,
                    )
            await self._set_user_role(target, role_change)

        # 激活状态（仅超级用户；SELF_DISABLE / LAST_ADMIN / ROOT_PROTECTED 已覆盖）
        if active_change is not None:
            if not actor.is_superuser:
                raise AuthorizationException(
                    message="仅超级管理员可修改账号状态",
                    error_code=ErrorCode.Authorization.PERMISSION_DENIED,
                )
            if actor.id == target.id and not active_change:
                raise AuthorizationException(
                    message="不能禁用自己的账号",
                    error_code=ErrorCode.Authorization.SELF_DISABLE,
                )
            if not active_change and self._is_admin_target(target):
                if await self._active_admin_count() <= 1:
                    raise ConflictException(
                        message="不能禁用最后一个管理员，请先提升其他用户为管理员",
                        error_code=ErrorCode.Authorization.LAST_ADMIN,
                    )
            if target.is_active != active_change:
                target.is_active = active_change
                if not active_change:
                    await self.refresh_repo.revoke_all_for_user(target.id)

            target.updated_at = now_utc()
            await self.user_repo.update(target)
            # 移除提前 commit：改由 _audit_admin 的 record_atomic 同事务原子提交，审计失败整体回滚
            await self.db.refresh(target)

        await self._audit_admin(
            action="user.update",
            actor=actor,
            target_id=target.id,
            detail={
                "changed_fields": list(update.model_dump(exclude_unset=True).keys()),
                "email": target.email,
                "username": target.username,
            },
            client_meta=client_meta,
        )
        return target

    async def set_user_active_admin(
        self,
        actor: User,
        target_user_id: int,
        *,
        active: bool,
        client_meta: Optional[dict] = None,
    ) -> User:
        """禁用/启用：普通管理员不可操作其他管理员；自禁/最后管理员/超管保护。"""
        target = await self.user_repo.get_user_with_roles(target_user_id)
        if target is None or target.deleted_at is not None:
            raise NotFoundException(
                message="用户不存在",
                resource_type="user",
                resource_id=str(target_user_id),
            )
        if target.is_superuser and not active:
            raise AuthorizationException(
                message="超级管理员账号不可被禁用",
                error_code=ErrorCode.Authorization.ROOT_PROTECTED,
            )
        if not actor.is_superuser:
            actor_roles = await self._admin_role_names(actor)
            if "admin" not in actor_roles:
                raise AuthorizationException(
                    message="权限不足",
                    error_code=ErrorCode.Authorization.PERMISSION_DENIED,
                )
            if self._is_admin_target(target):
                raise AuthorizationException(
                    message="普通管理员不可操作其他管理员账号",
                    error_code=ErrorCode.Authorization.FORBIDDEN,
                )
        if actor.id == target.id and not active:
            raise AuthorizationException(
                message="不能禁用自己的账号",
                error_code=ErrorCode.Authorization.SELF_DISABLE,
            )
        if (
            not active
            and self._is_admin_target(target)
            and await self._active_admin_count() <= 1
        ):
            raise ConflictException(
                message="不能禁用最后一个管理员，请先提升其他用户为管理员",
                error_code=ErrorCode.Authorization.LAST_ADMIN,
            )
        if target.is_active == active:
            raise ConflictException(
                message="状态无变化", error_code=ErrorCode.Validation.NO_CHANGE
            )

        target.is_active = active
        target.updated_at = now_utc()
        await self.user_repo.update(target)
        if not active:
            await self.refresh_repo.revoke_all_for_user(target.id)
        # 移除提前 commit：改由 _audit_admin 的 record_atomic 同事务原子提交，审计失败整体回滚
        await self.db.refresh(target)

        await self._audit_admin(
            action="user.enable" if active else "user.disable",
            actor=actor,
            target_id=target.id,
            detail={"to": active, "email": target.email, "username": target.username},
            client_meta=client_meta,
        )
        return target

    async def reset_password_admin(
        self,
        actor: User,
        target_user_id: int,
        *,
        default_password: bool,
        new_password: Optional[str] = None,
        client_meta: Optional[dict] = None,
    ) -> None:
        """重置密码：默认密码（普通管理员可用，目标须非管理员）或自定义（仅超管）。"""
        target = await self.user_repo.get_user_with_roles(target_user_id)
        if target is None or target.deleted_at is not None:
            raise NotFoundException(
                message="用户不存在",
                resource_type="user",
                resource_id=str(target_user_id),
            )
        if target.is_superuser:
            raise AuthorizationException(
                message="超级管理员账号不可被修改",
                error_code=ErrorCode.Authorization.ROOT_PROTECTED,
            )

        if default_password:
            if not settings.PASSWORD_RESET_DEFAULT:
                raise ConflictException(
                    message="未配置 PASSWORD_RESET_DEFAULT 环境变量",
                    error_code=ErrorCode.Validation.PASSWORD_RESET_NOT_CONFIGURED,
                )
            if not actor.is_superuser:
                actor_roles = await self._admin_role_names(actor)
                if "admin" not in actor_roles:
                    raise AuthorizationException(
                        message="权限不足",
                        error_code=ErrorCode.Authorization.PERMISSION_DENIED,
                    )
                if self._is_admin_target(target):
                    raise AuthorizationException(
                        message="普通管理员不可操作其他管理员账号",
                        error_code=ErrorCode.Authorization.FORBIDDEN,
                    )
            password = settings.PASSWORD_RESET_DEFAULT
        else:
            if not actor.is_superuser:
                raise AuthorizationException(
                    message="仅超级管理员可自定义重置密码",
                    error_code=ErrorCode.Authorization.PERMISSION_DENIED,
                )
            password = new_password or ""

        # 默认密码与自定义密码分支都须应用新密码哈希 + 撤销旧 refresh token
        target.hashed_password = await async_get_password_hash(password)
        target.password_changed_at = now_utc()
        target.updated_at = now_utc()
        await self.user_repo.update(target)
        await self.refresh_repo.revoke_all_for_user(target.id)
        # 移除提前 commit：改由 _audit_admin 的 record_atomic 同事务原子提交，审计失败整体回滚

        await self._audit_admin(
            action="user.reset_password",
            actor=actor,
            target_id=target.id,
            detail={
                "via": "default" if default_password else "custom",
                "email": target.email,
                "username": target.username,
            },
            client_meta=client_meta,
        )

    async def delete_user_admin(
        self,
        actor: User,
        target_user_id: int,
        client_meta: Optional[dict] = None,
    ) -> None:
        """硬删除用户（仅超级用户）：SELF_DELETE / ROOT_PROTECTED / LAST_ADMIN。"""
        if actor.id == target_user_id:
            raise AuthorizationException(
                message="不能删除自己的账号",
                error_code=ErrorCode.Authorization.SELF_DELETE,
            )
        target = await self.user_repo.get_user_with_roles(target_user_id)
        if target is None or target.deleted_at is not None:
            raise NotFoundException(
                message="用户不存在",
                resource_type="user",
                resource_id=str(target_user_id),
            )
        if target.is_superuser:
            raise AuthorizationException(
                message="超级管理员账号不可被删除",
                error_code=ErrorCode.Authorization.ROOT_PROTECTED,
            )
        if self._is_admin_target(target) and await self._active_admin_count() <= 1:
            raise ConflictException(
                message="不能删除最后一个管理员，请先提升其他用户为管理员",
                error_code=ErrorCode.Authorization.LAST_ADMIN,
            )

        # 级联清理（依赖 FK ondelete 的表由 PG 处理；无 FK 的显式清理）
        # C-16：原用裸 text("DELETE FROM <table> WHERE user_id=:i") 直查；
        # 下沉至各自 repo 的 delete_by_user 方法，去表名硬编码，走 ORM delete 语句。
        await self.refresh_repo.delete_by_user(target.id)
        await self.login_history_repo.delete_by_user(target.id)
        await self.password_history_repo.delete_by_user(target.id)
        await self.db.delete(target)
        # 移除提前 commit：改由 _audit_admin 的 record_atomic 同事务原子提交，审计失败整体回滚

        await self._audit_admin(
            action="user.delete",
            actor=actor,
            target_id=None,
            detail={"deleted_user_id": target.id, "email": target.email},
            client_meta=client_meta,
        )

    # ------------------------------------------------------------------ 内部

    async def _admin_role_names(self, user: User) -> set[str]:
        await self.db.refresh(user, ["roles"])
        return {r.name for r in user.roles}

    def _is_admin_target(self, user: User) -> bool:
        return user.is_superuser or any(r.name == "admin" for r in user.roles)

    async def _active_admin_count(self) -> int:
        """活跃管理员数量（is_superuser 或持有 admin 角色）。"""
        return await self.user_repo.count_active_admins()

    async def _set_user_role(self, user: User, role_name: str) -> None:
        """替换用户角色为单一角色（前端语义：一用户一主角色）。"""
        role = await self.rbac_repo.get_role_by_name(role_name)
        if role is None:
            raise NotFoundException(
                message=f"角色 {role_name} 不存在",
                resource_type="role",
                resource_id=role_name,
            )
        await self.db.refresh(user, ["roles"])
        user.roles = [role]

    async def _audit_admin(
        self,
        *,
        action: str,
        actor: User,
        target_id: Optional[int],
        detail: dict,
        client_meta: Optional[dict],
    ) -> None:
        # 原子提交：审计与主操作同事务；审计写失败整体回滚（管理员审计不丢，门槛#2）
        await self.audit.record_atomic(
            action=action,
            resource_type="user",
            resource_id=str(target_id) if target_id else None,
            actor_id=actor.id,
            actor_username=actor.username,
            detail=detail,
            **(client_meta or {}),
        )
