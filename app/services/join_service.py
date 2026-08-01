"""入社申请服务：提交（游客/登录均可）+ 我的申请 + 管理员审批。

审批通过/拒绝时：写审计 + 向关联用户发送站内通知（失败不阻断审批）。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, ErrorCode, NotFoundException
from app.models.join_application import JoinApplication
from app.repositories.join_application_repo import JoinApplicationRepository
from app.schemas.join import JoinApplicationInput
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService


class JoinService:
    def __init__(self, db: AsyncSession, audit: Optional[AuditService] = None):
        self.db = db
        self.repo = JoinApplicationRepository(db)
        self.audit = audit if audit is not None else AuditService()

    async def submit(
        self, data: JoinApplicationInput, user_id: Optional[int] = None
    ) -> JoinApplication:
        payload = data.model_dump()
        payload["user_id"] = user_id
        obj = await self.repo.create(payload)
        await self.db.commit()
        return obj

    async def list_mine(self, user_id: int) -> list[JoinApplication]:
        return await self.repo.list_for_user(user_id)

    async def list_all(self, status: Optional[str] = None) -> list[JoinApplication]:
        return await self.repo.list(status)

    async def review(
        self,
        application_id: int,
        *,
        status: str,
        admin_id: int,
        admin_username: str,
        review_note: Optional[str] = None,
        client_meta: Optional[dict] = None,
    ) -> JoinApplication:
        app = await self.repo.get_by_id(application_id)
        if app is None:
            raise NotFoundException(
                message="申请不存在",
                resource_type="join_application",
                resource_id=str(application_id),
            )
        if app.status != "pending":
            raise ConflictException(
                message="该申请已处理",
                error_code=ErrorCode.Validation.ALREADY_REVIEWED,
            )

        await self.repo.review(
            app,
            status=status,
            reviewed_by=admin_id,
            review_note=review_note,
        )
        await self.db.commit()

        await self.audit.record(
            action=f"join.{'approve' if status == 'approved' else 'reject'}",
            resource_type="join_application",
            resource_id=str(app.id),
            actor_id=admin_id,
            actor_username=admin_username,
            detail={
                "applicant_name": app.applicant_name,
                "student_id": app.student_id,
                "review_note": review_note or None,
            },
            **(client_meta or {}),
        )

        # 关联用户站内通知（失败不阻断审批，仅记日志）
        if app.user_id is not None:
            try:
                notification_service = NotificationService(self.db)
                title = "入社申请已通过" if status == "approved" else "入社申请未通过"
                greeting = (
                    "恭喜！你的入社申请已通过。"
                    if status == "approved"
                    else "你的入社申请未通过。"
                )
                content = greeting + (f" 备注：{review_note}" if review_note else "")
                await notification_service.create(
                    user_id=app.user_id,
                    type="admin",
                    title=title,
                    content=content,
                    sender_id=admin_id,
                )
            except Exception:  # noqa: BLE001 - 通知失败不阻断审批
                from app.core.loguru_logger import get_logger

                get_logger("join").warning(
                    "入社审批通知发送失败", application_id=app.id
                )
        return app
