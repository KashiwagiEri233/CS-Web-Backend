"""密码重置申请服务：用户提交申请 → 管理员批准（重置为默认密码）/ 拒绝。

与前端语义对齐（src/modules/auth/server/password-reset.ts）：
- 申请免登录但需邮箱校验 + 限流（限流在路由层）
- 批准/拒绝须管理员（路由层 require_permission）
- SELF_APPROVE：管理员不能批准自己的申请（防接管）
- 批准后：密码更新 + refresh token 全失效 + 申请状态更新，同一事务原子提交
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
from app.models.password_reset_request import PasswordResetRequest
from app.repositories.password_reset_request_repo import PasswordResetRequestRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_service import AuditService


class PasswordResetService:
    """忘记密码申请-审批流。repo 只 flush，本服务显式 commit。"""

    def __init__(self, db: AsyncSession, audit: Optional[AuditService] = None):
        self.db = db
        self.repo = PasswordResetRequestRepository(db)
        self.user_repo = UserRepository(db)
        # 默认注入共享请求会话，使 record_atomic 可同事务提交审计（否则 db=None 会抛错）
        self.audit = audit if audit is not None else AuditService(self.db)

    async def create_request(self, email: str) -> dict:
        """创建申请；已有 pending 申请时直接返回已有 id。"""
        normalized = email.lower()
        existing = await self.repo.get_pending_for_email(normalized)
        if existing is not None:
            return {"id": existing.id}
        req = await self.repo.create(normalized)
        await self.db.commit()
        return {"id": req.id}

    async def list_requests(
        self, status: Optional[str] = None
    ) -> list[PasswordResetRequest]:
        return await self.repo.list(status)

    async def approve_request(
        self,
        request_id: int,
        admin_id: int,
        admin_username: str,
        note: Optional[str] = None,
        client_meta: Optional[dict] = None,
    ) -> PasswordResetRequest:
        """批准申请：重置为默认密码 + 撤销用户全部 refresh token + 状态更新，原子提交。"""
        req = await self._get_pending_or_raise(request_id)

        user = await self.user_repo.get_by_email(req.email)
        if user is None:
            raise NotFoundException(
                message="用户不存在", resource_type="user", resource_id=req.email
            )

        if user.id == admin_id:
            raise AuthorizationException(
                message="不能批准自己的密码重置申请",
                error_code=ErrorCode.Authorization.SELF_APPROVE,
            )

        default_password = settings.PASSWORD_RESET_DEFAULT
        if not default_password:
            raise ConflictException(
                message="未配置 PASSWORD_RESET_DEFAULT 环境变量，无法执行默认密码重置",
                error_code=ErrorCode.Validation.PASSWORD_RESET_NOT_CONFIGURED,
            )

        user.hashed_password = await async_get_password_hash(default_password)
        user.password_changed_at = now_utc()
        user.updated_at = now_utc()
        # 密码更新后使改密前签发的 access token 立即失效（JWT pwd_at 对比）
        await self._revoke_user_refresh_tokens(user.id)
        await self.repo.resolve(
            request=req,
            status="approved",
            admin_id=admin_id,
            admin_note=note,
        )
        # 移除提前 commit：改由 record_atomic 同事务原子提交，审计写失败则整体回滚，杜绝审计丢失
        await self.audit.record_atomic(
            action="password_reset.approve",
            resource_type="password_reset_request",
            resource_id=str(req.id),
            actor_id=admin_id,
            actor_username=admin_username,
            detail={"email": req.email, "note": note or None},
            **(client_meta or {}),
        )
        return req

    async def reject_request(
        self,
        request_id: int,
        admin_id: int,
        admin_username: str,
        note: Optional[str] = None,
        client_meta: Optional[dict] = None,
    ) -> PasswordResetRequest:
        """拒绝申请。"""
        req = await self._get_pending_or_raise(request_id)
        await self.repo.resolve(
            request=req,
            status="rejected",
            admin_id=admin_id,
            admin_note=note,
        )
        # 移除提前 commit：改由 record_atomic 同事务原子提交，审计写失败则整体回滚
        await self.audit.record_atomic(
            action="password_reset.reject",
            resource_type="password_reset_request",
            resource_id=str(req.id),
            actor_id=admin_id,
            actor_username=admin_username,
            detail={"email": req.email, "note": note or None},
            **(client_meta or {}),
        )
        return req

    # ------------------------------------------------------------------ 内部

    async def _get_pending_or_raise(self, request_id: int) -> PasswordResetRequest:
        req = await self.repo.get_by_id(request_id)
        if req is None:
            raise NotFoundException(
                message="申请不存在",
                resource_type="password_reset_request",
                resource_id=str(request_id),
            )
        if req.status != "pending":
            raise ConflictException(
                message="该申请已被处理",
                error_code=ErrorCode.Validation.ALREADY_PROCESSED,
            )
        return req

    async def _revoke_user_refresh_tokens(self, user_id: int) -> None:
        """撤销用户全部 refresh token（改密后旧 token 失效）。"""
        from app.repositories.refresh_token_repo import RefreshTokenRepository

        await RefreshTokenRepository(self.db).revoke_all_for_user(user_id)
