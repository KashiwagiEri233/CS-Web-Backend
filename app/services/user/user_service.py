"""用户管理服务：用户 CRUD（列表/查询/更新/删除）+ 管理员操作。

职责边界：
- 本服务管用户实体增删改查与字段校验（自我管理域）。
- 管理员操作（列表/编辑/启停/重置密码/硬删除）同文件内，共用审计与角色内部方法。
- 改密时在同一事务内撤销 refresh（组合 Auth/Refresh 仓储，一次 commit）。
- 删除为软删除（deleted_at），列表默认不返回已删用户。

C-17 拆分记录：个人资料域（profile 读写/头像/公开主页）已迁至
``app.services.user.profile_service.ProfileService``（第一切片，2026-10）。
"""

from __future__ import annotations

from typing import Optional, Tuple
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ErrorCode,
    InvalidCredentialsException,
    NotFoundException,
    PermissionDeniedException,
    ValidationException,
)
from app.core.security import async_get_password_hash, async_verify_password
from app.core.config import settings
from app.core.timezone import now_utc
from app.models.role import Role
from app.models.user import User
from app.repositories.base import paginate
from app.repositories.login_history_repo import LoginHistoryRepository
from app.repositories.password_history_repo import PasswordHistoryRepository
from app.repositories.rbac_repo import RBACRepository
from app.repositories.refresh_token_repo import RefreshTokenRepository
from app.repositories.user_repo import UserRepository
from app.schemas.auth import UserOut
from app.schemas.pagination import compute_total_pages
from app.schemas.user import AdminUserUpdate
from app.services.audit_service import AuditService


def to_admin_out(user: User) -> dict:
    """UserOut + roles（前端管理员视图需要角色列表；admin_users 路由与 user_service 共用，波次 B2 收敛）。"""
    base = UserOut.model_validate(user).model_dump()
    base["roles"] = [r.name for r in user.roles]
    return base


class UserService:
    """用户管理服务（CRUD）。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.refresh_repo = RefreshTokenRepository(db)
        self.login_history_repo = LoginHistoryRepository(db)
        self.password_history_repo = PasswordHistoryRepository(db)
        self.rbac_repo = RBACRepository(db)
        # 注入共享请求会话，使 record_atomic 可同事务提交审计（否则 db=None 会抛错）；与 auth_service 一致
        self.audit = AuditService(self.db)

    async def list_users(self, skip: int = 0, limit: int = 100) -> Tuple[list, int]:
        """分页获取未删除用户列表，返回 (users, total)。"""
        users = await self.user_repo.list_active(skip=skip, limit=limit)
        total = await self.user_repo.count_active()
        return users, total

    async def get_user(self, user_id: int) -> User:
        """获取指定未删除用户；不存在抛 NotFoundException。"""
        user = await self.user_repo.get_by_id(user_id)
        if user is None or user.deleted_at is not None:
            raise NotFoundException(
                message="用户不存在",
                resource_type="user",
                resource_id=user_id,
            )
        return user

    async def update_user(
        self,
        user_id: int,
        update_data: dict,
        commit: bool = True,
        actor: Optional[User] = None,
    ) -> User:
        """更新指定用户字段（含改密时同事务撤 refresh）。

        提权防护：目标为超级用户时要求 actor 也是超级用户（与角色分配同标准，
        防止持有 user:update 权限的角色停用/改密超管接管系统）。
        """
        user = await self.get_user(user_id)
        self._check_superuser_manipulation(user, actor)
        email_conflicts = await self._email_conflicts(user_id, update_data)
        password_changed = await self._apply_update(user, update_data, email_conflicts)
        try:
            await self.user_repo.update(user)
            if password_changed:
                await self.refresh_repo.revoke_all_for_user(user_id)
            if commit:
                await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictException(message="用户名或邮箱已存在") from exc
        if commit:
            await self.db.refresh(user)
        return user

    async def update_profile(self, user: User, update_data: dict) -> User:
        """当前用户自助更新（不可改 is_active；改密需旧密码，同事务撤 refresh）。"""
        await self._verify_old_password(user, update_data)
        email_conflicts = await self._email_conflicts(user.id, update_data)
        password_changed = await self._apply_update(
            user,
            update_data,
            email_conflicts=email_conflicts,
            allow_active=False,
        )
        await self.user_repo.update(user)
        if password_changed:
            await self.refresh_repo.revoke_all_for_user(user.id)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictException(message="邮箱已被其他用户使用") from exc
        await self.db.refresh(user)
        return user

    async def delete_user(self, user_id: int, actor: User, commit: bool = True) -> None:
        """软删除用户。禁止自删；不存在抛 NotFoundException。

        同事务撤销全部 refresh，使会话立即失效。
        提权防护：目标为超级用户时要求 actor 也是超级用户。
        """
        if user_id == actor.id:
            raise ConflictException(
                message="不能删除自己",
                details={"user_id": user_id},
            )
        user = await self.get_user(user_id)
        self._check_superuser_manipulation(user, actor)
        user.deleted_at = now_utc()
        user.is_active = False
        # 释放 username/email 唯一约束，便于同名重新注册。
        # username 列长 50：后缀约 21 字符，原名截断后拼接，避免 String(50) 溢出。
        stamp = int(now_utc().timestamp())
        suffix = f"__del_{user.id}_{stamp}"
        max_base = max(1, 50 - len(suffix))
        user.username = f"{user.username[:max_base]}{suffix}"
        user.email = f"del_{stamp}_{user.id}@invalid.local"
        await self.user_repo.update(user)
        await self.refresh_repo.revoke_all_for_user(user_id)
        if commit:
            await self.db.commit()

    # -------------------------------------------------------- 管理员操作（Phase 2）

    async def _admin_role_names(self, user: User) -> set[str]:
        await self.db.refresh(user, ["roles"])
        return {r.name for r in user.roles}

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

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _check_superuser_manipulation(user: User, actor: Optional[User]) -> None:
        """阻止非超级用户操纵超级用户账号（改密/停用/软删等效于接管系统）。

        与 rbac_assignments._check_privilege_escalation 同一防护标准；
        actor=None 视为可信内部调用（脚本/种子初始化），放行。
        """
        if actor is None or actor.is_superuser:
            return
        if user.is_superuser:
            raise PermissionDeniedException(required_permissions=["superuser"])

    @staticmethod
    async def _verify_old_password(user: User, update_data: dict) -> None:
        """自助改密前置校验：提供新密码时必须附带正确的旧密码。

        access token 短暂泄露（XSS/日志）即可改密并吊销全部会话，旧密码校验把
        "持有 token"升级为"知道密码"，阻断该接管路径。old_password 消费后即弹出，
        不会进入字段更新流程。
        """
        old_password = update_data.pop("old_password", None)
        if update_data.get("password") is None:
            return
        if not old_password:
            raise ValidationException(
                message="修改密码必须提供当前密码",
                details={"field": "old_password"},
            )
        if not await async_verify_password(old_password, user.hashed_password):
            raise InvalidCredentialsException(
                details={"reason": "old password incorrect"}
            )

    async def _email_conflicts(self, self_id: int, update_data: dict) -> bool:
        email = update_data.get("email")
        if email is None:
            return False
        existing = await self.user_repo.get_by_email(email)
        return (
            existing is not None
            and existing.id != self_id
            and existing.deleted_at is None
        )

    @staticmethod
    async def _apply_update(
        user: User,
        update_data: dict,
        email_conflicts: bool,
        allow_active: bool = True,
    ) -> bool:
        """应用字段更新。返回是否发生了改密。"""
        if email_conflicts:
            raise ConflictException(
                message="邮箱已被其他用户使用",
                details={"email": update_data.get("email")},
            )

        password_changed = False
        if "email" in update_data and update_data["email"] is not None:
            user.email = update_data["email"]
        if "full_name" in update_data:
            user.full_name = update_data["full_name"]
        if update_data.get("password") is not None:
            user.hashed_password = await async_get_password_hash(
                update_data["password"]
            )
            user.password_changed_at = now_utc()
            password_changed = True
        if allow_active and update_data.get("is_active") is not None:
            user.is_active = update_data["is_active"]
        return password_changed
