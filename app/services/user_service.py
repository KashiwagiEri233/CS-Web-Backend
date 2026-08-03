"""用户管理服务：负责用户 CRUD（列表/查询/更新/删除）+ 个人资料（Phase 1 迁移）。

职责边界：
- 本服务管用户实体增删改查与字段校验。
- 改密时在同一事务内撤销 refresh（组合 Auth/Refresh 仓储，一次 commit）。
- 删除为软删除（deleted_at），列表默认不返回已删用户。
- 个人资料：profile 读写、预设/上传头像、公开主页（含论坛/考试统计）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple
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
from app.models.user import User
from app.repositories.activity_participation_repo import ActivityParticipationRepository
from app.repositories.refresh_token_repo import RefreshTokenRepository
from app.repositories.user_repo import UserRepository
from app.schemas.profile import ProfileUpdate
from app.schemas.user import AdminUserUpdate
from app.utils.image_validate import is_valid_image_mime

# 预设头像（与前端 src/shared/config/avatar-presets.ts 对齐；文件由前端静态服务）
_PRESET_AVATAR_URL = "/avatars/presets/preset-{id}.svg"
_PRESET_COUNT = 6

# 头像上传限制（与前端一致）
AVATAR_MAX_SIZE = 2 * 1024 * 1024
AVATAR_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
AVATAR_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

_DATA_DIR = Path("data")
_AVATARS_DIR = _DATA_DIR / "avatars"


class UserService:
    """用户管理服务（CRUD）。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.refresh_repo = RefreshTokenRepository(db)
        self.activity_repo = ActivityParticipationRepository(db)

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
        from sqlalchemy import func, or_, select
        from sqlalchemy.orm import selectinload

        page = max(1, page)
        page_size = min(max(1, page_size), 200)

        conditions: list = [User.deleted_at.is_(None)]
        if search:
            kw = f"%{search}%"
            conditions.append(or_(User.email.ilike(kw), User.display_name.ilike(kw)))
        if active == "active":
            conditions.append(User.is_active.is_(True))
        elif active == "inactive":
            conditions.append(User.is_active.is_(False))

        total = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(User).where(*conditions)
                )
            ).scalar_one()
        )
        stmt = (
            select(User)
            .options(selectinload(User.roles))
            .where(*conditions)
            .order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        users = list((await self.db.execute(stmt)).scalars().all())

        # role 筛选（角色走关联表，查询后过滤）
        if role != "all":
            users = [u for u in users if role in {r.name for r in u.roles}]

        return {
            "users": users,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
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
        await self.db.commit()
        await self.db.refresh(target)

        await self._audit_admin(
            action="user.update",
            actor=actor,
            target_id=target.id,
            detail={
                "changed_fields": list(update.model_dump(exclude_unset=True).keys())
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
        await self.db.commit()
        await self.db.refresh(target)

        await self._audit_admin(
            action="user.enable" if active else "user.disable",
            actor=actor,
            target_id=target.id,
            detail={"to": active},
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

        target.hashed_password = await async_get_password_hash(password)
        target.password_changed_at = now_utc()
        target.updated_at = now_utc()
        await self.user_repo.update(target)
        await self.refresh_repo.revoke_all_for_user(target.id)
        await self.db.commit()

        await self._audit_admin(
            action="user.reset_password",
            actor=actor,
            target_id=target.id,
            detail={"via": "default" if default_password else "custom"},
            client_meta=client_meta,
        )

    async def delete_user_admin(
        self,
        actor: User,
        target_user_id: int,
        client_meta: Optional[dict] = None,
    ) -> None:
        """硬删除用户（仅超级用户）：SELF_DELETE / ROOT_PROTECTED / LAST_ADMIN。"""
        from sqlalchemy import text

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
        for table in ("refresh_tokens", "login_history", "password_history"):
            await self.db.execute(
                text(f"DELETE FROM {table} WHERE user_id=:i"), {"i": target.id}
            )
        await self.db.delete(target)
        await self.db.commit()

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
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        rows = (
            (
                await self.db.execute(
                    select(User)
                    .where(User.is_active.is_(True), User.deleted_at.is_(None))
                    .options(selectinload(User.roles))
                )
            )
            .scalars()
            .all()
        )
        return sum(1 for u in rows if self._is_admin_target(u))

    async def _set_user_role(self, user: User, role_name: str) -> None:
        """替换用户角色为单一角色（前端语义：一用户一主角色）。"""
        from sqlalchemy import select

        from app.models.role import Role

        role = (
            await self.db.execute(select(Role).where(Role.name == role_name))
        ).scalar_one_or_none()
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
        from app.services.audit_service import AuditService

        await AuditService().record(
            action=action,
            resource_type="user",
            resource_id=str(target_id) if target_id else None,
            actor_id=actor.id,
            actor_username=actor.username,
            detail=detail,
            **(client_meta or {}),
        )

    # -------------------------------------------------------- 个人资料（Phase 1）

    async def get_profile(self, user_id: int) -> dict:
        """当前用户完整资料：用户 + 活动参与记录。"""
        user = await self.get_user(user_id)
        activities = await self.activity_repo.list_for_user(user_id)
        return {"user": user, "activities": activities}

    async def update_profile_fields(self, user_id: int, update: ProfileUpdate) -> User:
        """更新个人资料业务字段（display_name/bio/github_url/website_url/tech_tags）。"""
        user = await self.get_user(user_id)

        data = update.model_dump(exclude_unset=True)
        sets: dict = {}
        if "display_name" in data:
            sets["display_name"] = data["display_name"]
        if "bio" in data:
            sets["bio"] = data["bio"]
        if "github_url" in data:
            sets["github_url"] = data["github_url"]
        if "website_url" in data:
            sets["website_url"] = data["website_url"]
        if "tech_tags" in data:
            tags = data["tech_tags"] or []
            if len(tags) > 20:
                raise ValidationException(
                    message="技术标签数量超出上限",
                    error_code=ErrorCode.Validation.VALIDATION_FAILED,
                )
            sets["tech_tags"] = tags

        if sets:
            for key, value in sets.items():
                setattr(user, key, value)
            user.updated_at = now_utc()
            await self.user_repo.update(user)
            await self.db.commit()
            await self.db.refresh(user)
        return user

    async def set_preset_avatar(self, user_id: int, preset_id: int) -> User:
        """设置预设头像（avatar_type=preset）。"""
        if preset_id < 1 or preset_id > _PRESET_COUNT:
            raise ValidationException(
                message="无效的预设头像 ID",
                error_code=ErrorCode.Validation.INVALID_PRESET,
            )
        user = await self.get_user(user_id)
        user.avatar_url = _PRESET_AVATAR_URL.format(id=preset_id)
        user.avatar_type = "preset"
        user.updated_at = now_utc()
        await self.user_repo.update(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def save_uploaded_avatar(
        self,
        user_id: int,
        content: bytes,
        mime_type: str,
        original_name: str,
        client_meta: Optional[dict] = None,
    ) -> User:
        """保存上传的头像：大小/MIME/扩展名/魔数四重校验，文件名服务端生成。"""
        if len(content) > AVATAR_MAX_SIZE:
            raise ValidationException(
                message=f"文件大小不能超过 {AVATAR_MAX_SIZE // 1024 // 1024}MB",
                error_code=ErrorCode.Validation.FILE_TOO_LARGE,
            )
        if mime_type not in AVATAR_ALLOWED_MIME:
            raise ValidationException(
                message="仅支持 JPEG / PNG / WebP / GIF 格式",
                error_code=ErrorCode.Validation.INVALID_FILE_TYPE,
            )
        ext = Path(original_name).suffix.lower()
        if ext not in AVATAR_ALLOWED_EXT:
            raise ValidationException(
                message="文件扩展名不被允许",
                error_code=ErrorCode.Validation.INVALID_FILE_TYPE,
            )
        if not is_valid_image_mime(content, mime_type):
            raise ValidationException(
                message="文件内容与声明类型不匹配",
                error_code=ErrorCode.Validation.INVALID_FILE_TYPE,
            )

        user = await self.get_user(user_id)
        _AVATARS_DIR.mkdir(parents=True, exist_ok=True)

        # 文件名服务端生成：user<id>-<timestamp><ext>，不使用原始文件名
        filename = f"user{user_id}-{int(now_utc().timestamp() * 1000)}{ext}"
        try:
            (_AVATARS_DIR / filename).write_bytes(content)
        except OSError as exc:
            raise ValidationException(
                message="头像保存失败",
                error_code=ErrorCode.Validation.FILE_SAVE_FAILED,
            ) from exc

        # 删除旧上传头像（仅 uploaded 类型）
        if user.avatar_type == "uploaded" and user.avatar_url:
            old_name = Path(user.avatar_url).name
            if old_name and old_name != filename:
                try:
                    (_AVATARS_DIR / old_name).unlink(missing_ok=True)
                except OSError:
                    pass  # 旧文件删除失败不阻塞流程

        user.avatar_url = f"/api/avatars/{filename}"
        user.avatar_type = "uploaded"
        user.updated_at = now_utc()
        await self.user_repo.update(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def get_public_profile(self, user_id: int) -> Optional[dict]:
        """用户公开主页（无需登录）：公开资料 + 社区/考试统计。"""
        from sqlalchemy import func, select
        from app.models.community import CommunityComment, CommunityPost
        from app.models.exam import Exam, ExamAttempt, ExamQuestion

        user = await self.user_repo.get_by_id(user_id)
        if user is None or user.deleted_at is not None or not user.is_active:
            return None

        topic_count = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(CommunityPost)
                    .where(
                        CommunityPost.author_id == user_id,
                        CommunityPost.kind == "topic",
                        CommunityPost.status == "published",
                    )
                )
            ).scalar_one()
        )
        reply_count = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(CommunityComment)
                    .where(
                        CommunityComment.author_id == user_id,
                        CommunityComment.status == "published",
                    )
                )
            ).scalar_one()
        )
        exam_count = int(
            (
                await self.db.execute(
                    select(func.count(func.distinct(ExamAttempt.exam_id)))
                    .join(Exam, Exam.id == ExamAttempt.exam_id)
                    .where(ExamAttempt.user_id == user_id, Exam.status == "ended")
                )
            ).scalar_one()
        )
        # 通过数：参与且已结束的考试中，得分合计 ≥ 总分 60% 的考试数（与前端语义一致）
        per_exam = (
            select(
                ExamAttempt.exam_id,
                func.sum(ExamAttempt.score).label("got"),
                func.sum(ExamQuestion.score).label("total"),
            )
            .join(ExamQuestion, ExamQuestion.exam_id == ExamAttempt.exam_id)
            .where(ExamAttempt.user_id == user_id)
            .group_by(ExamAttempt.exam_id)
            .subquery()
        )
        exam_passed_count = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(per_exam)
                    .where(
                        func.coalesce(per_exam.c.got, 0)
                        >= func.coalesce(per_exam.c.total, 0) * 0.6
                    )
                )
            ).scalar_one()
        )

        return {
            "user": {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "bio": user.bio,
                "avatar_url": user.avatar_url,
                "avatar_type": user.avatar_type or "initial",
                "github_url": user.github_url,
                "website_url": user.website_url,
                "tech_tags": user.tech_tags or [],
                "created_at": user.created_at,
            },
            "stats": {
                "topic_count": topic_count,
                "reply_count": reply_count,
                "exam_count": exam_count,
                "exam_passed_count": exam_passed_count,
            },
        }

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
