"""任务读写与执行编排（P3）。

事务约定：本 service 只 flush，不 commit；路由层通过审计 `record_atomic`
在同一会话提交业务、资金、幂等与审计。
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationException,
    BaseAppException,
    ConflictException,
    ErrorCode,
    NotFoundException,
    ValidationException,
)
from app.core.timezone import now_utc
from app.models.organization import Peak
from app.models.task import (
    EXECUTION_MODE_SINGLE,
    EXECUTION_MODE_TEAM,
    TASK_STATUS_DRAFT,
    TASK_STATUS_EXPIRED,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_PENDING_REVIEW,
    TASK_STATUS_PUBLISHED,
    TASK_STATUS_REJECTED,
    TASK_STATUS_SUBMITTED,
    VISIBILITY_PEAK,
    Task,
)
from app.models.user import User
from app.repositories.task_repo import TaskRepository
from app.repositories.team_repo import TeamRepository
from app.schemas.task import ClaimCreate, SubmissionCreate, TaskCreate, TaskUpdate
from app.services.rbac.rbac_service import RBACService
from app.services.task.access import (
    can_view_task,
    claim_to_dict,
    get_publisher_name,
    load_active_member,
    require_active_member,
    require_future,
    task_to_dict,
    visibility_conditions,
)
from app.services.task.settlement import refund_reward
from app.services.wallet.idempotency_service import (
    IdempotencyService,
    require_idempotency_key,
)

# 已发布后允许修改的展示字段；资金/范围/人数/模式必须关闭后新建。
_PUBLISHED_EDITABLE_FIELDS = frozenset(
    {"title", "description", "content_markdown", "difficulty", "category", "tags"}
)

_OP_CREATE = "task_create"
_OP_UPDATE = "task_update"
_OP_REVIEW_REQUEST = "task_review_request"
_OP_ARCHIVE = "task_archive"
_OP_CLAIM = "task_claim"
_OP_CANCEL = "task_cancel"
_OP_SUBMIT = "task_submit"


def check_if_match(expected: Optional[str], current: int) -> None:
    """If-Match 解析：缺失 428，失配 412。"""
    if expected is None:
        raise BaseAppException(
            message="缺少 If-Match 版本",
            error_code=ErrorCode.Conflict.VERSION_REQUIRED,
            status_code=428,
        )
    value = expected.strip().strip('"')
    if not value.isdigit():
        raise ValidationException(message="If-Match 必须为整数版本")
    if int(value) != current:
        raise BaseAppException(
            message="版本已变化，请刷新后重试",
            error_code=ErrorCode.Conflict.VERSION_MISMATCH,
            status_code=412,
            details={"current_version": current},
        )


def _task_not_found(task_id: int) -> NotFoundException:
    return NotFoundException(
        message="任务不存在", resource_type="task", resource_id=str(task_id)
    )


def _claim_not_found(claim_id: int) -> NotFoundException:
    return NotFoundException(
        message="执行记录不存在", resource_type="task_claim", resource_id=str(claim_id)
    )


class TaskService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TaskRepository(db)
        self.team_repo = TeamRepository(db)
        self.idem = IdempotencyService(db)

    # ------------------------------------------------------------------ 内部

    async def _get_task(self, task_id: int) -> Task:
        task = await self.repo.get(task_id)
        if task is None:
            raise _task_not_found(task_id)
        return task

    async def _begin(
        self,
        *,
        actor_id: int,
        operation: str,
        key: Optional[str],
        payload: dict,
    ) -> tuple[str, Optional[dict]]:
        key = require_idempotency_key(key)
        replay = await self.idem.replay(
            actor_id=actor_id, operation=operation, key=key, payload=payload
        )
        return key, replay

    async def _save(
        self,
        *,
        actor_id: int,
        operation: str,
        key: str,
        payload: dict,
        response: dict,
    ) -> dict:
        await self.idem.save(
            actor_id=actor_id,
            operation=operation,
            key=key,
            payload=payload,
            response=response,
        )
        return response

    async def _add_action(
        self,
        *,
        task: Task,
        actor_id: int,
        action: str,
        from_status: Optional[str],
        claim_id: Optional[int] = None,
        reason: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        await self.repo.add_action(
            {
                "task_id": task.id,
                "claim_id": claim_id,
                "actor_id": actor_id,
                "action": action,
                "from_status": from_status,
                "to_status": task.status,
                "reason": reason,
                "request_id": request_id,
            }
        )

    # ------------------------------------------------------------------ 读

    async def list_tasks(
        self,
        *,
        actor: User,
        status: Optional[str] = None,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[List[dict], int]:
        member = await load_active_member(self.db, actor.id)
        conditions = list(visibility_conditions(actor.id, member))
        if status:
            conditions.append(Task.status == status)
        else:
            conditions.append(Task.status == TASK_STATUS_PUBLISHED)
        if category:
            conditions.append(Task.category == category)
        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(
                or_(Task.title.ilike(pattern), Task.description.ilike(pattern))
            )
        rows = await self.repo.list_tasks(
            conditions=conditions, skip=skip, limit=limit
        )
        total = await self.repo.count_tasks(conditions=conditions)
        return [task_to_dict(row) for row in rows], total

    async def get_task(self, *, actor: User, task_id: int) -> dict:
        task = await self._get_task(task_id)
        member = await load_active_member(self.db, actor.id)
        if not can_view_task(task, actor.id, member):
            raise AuthorizationException(
                message="无权查看该任务",
                error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
            )
        result = task_to_dict(
            task, await get_publisher_name(self.db, task.publisher_id)
        )
        claim = await self.repo.get_open_claim(task.id)
        if claim is not None:
            members = await self.repo.list_claim_members(claim.id)
            result["active_claim"] = claim_to_dict(claim, members)
        return result

    async def list_my_published(
        self, *, actor: User, skip: int = 0, limit: int = 20
    ) -> tuple[List[dict], int]:
        conditions = [Task.publisher_id == actor.id]
        rows = await self.repo.list_tasks(
            conditions=conditions, skip=skip, limit=limit
        )
        total = await self.repo.count_tasks(conditions=conditions)
        return [task_to_dict(row) for row in rows], total

    async def list_my_claims(
        self, *, actor: User, skip: int = 0, limit: int = 20
    ) -> tuple[List[dict], int]:
        claims = await self.repo.list_claims_for_user(
            actor.id, skip=skip, limit=limit
        )
        items = []
        for claim in claims:
            members = await self.repo.list_claim_members(claim.id)
            submission = await self.repo.latest_submission(claim.id)
            task = await self.repo.get(claim.task_id)
            items.append(claim_to_dict(claim, members, submission, task))
        total = await self.repo.count_claims_for_user(actor.id)
        return items, total

    async def list_claims(
        self, *, actor: User, task_id: int
    ) -> List[dict]:
        task = await self._get_task(task_id)
        claims = await self.repo.list_claims_for_task(task_id)
        visible = task.publisher_id == actor.id or actor.is_superuser
        if not visible:
            visible = any(
                any(member.user_id == actor.id for member, _ in await self.repo.list_claim_members(claim.id))
                for claim in claims
            )
        if not visible:
            permissions = await RBACService(self.db).get_user_permissions(
                actor.id, getattr(actor, "authorization_version", None)
            )
            visible = bool({"task:review", "task:accept"} & permissions)
        if not visible:
            raise AuthorizationException(
                message="无权查看该任务的执行记录",
                error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
            )
        items = []
        for claim in claims:
            members = await self.repo.list_claim_members(claim.id)
            submission = await self.repo.latest_submission(claim.id)
            items.append(claim_to_dict(claim, members, submission, task))
        return items

    async def list_history(
        self, *, actor: User, task_id: int, skip: int = 0, limit: int = 50
    ) -> tuple[list, int]:
        task = await self._get_task(task_id)
        claim = await self.repo.get_open_claim(task_id)
        allowed = task.publisher_id == actor.id or actor.is_superuser
        if not allowed and claim is not None:
            members = await self.repo.list_claim_members(claim.id)
            allowed = any(member.user_id == actor.id for member, _ in members)
        if not allowed:
            raise AuthorizationException(
                message="无权查看该任务历史",
                error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
            )
        rows = await self.repo.list_actions(task_id, skip=skip, limit=limit)
        total = await self.repo.count_actions(task_id)
        return rows, total

    # ------------------------------------------------------------------ 写

    async def create_task(
        self,
        *,
        actor: User,
        data: TaskCreate,
        idempotency_key: Optional[str],
        request_id: Optional[str] = None,
    ) -> dict:
        payload = data.model_dump(mode="json")
        key, replay = await self._begin(
            actor_id=actor.id, operation=_OP_CREATE, key=idempotency_key, payload=payload
        )
        if replay is not None:
            return replay
        require_future(data.deadline)
        if data.visibility == VISIBILITY_PEAK:
            peak = await self.db.get(Peak, data.peak_id)
            if peak is None or peak.archived_at is not None or not peak.is_active:
                raise ValidationException(message="指定的峰不存在或已归档")

        task = await self.repo.create(
            {
                "title": data.title,
                "description": data.description,
                "content_markdown": data.content_markdown,
                "difficulty": data.difficulty,
                "category": data.category,
                "tags": list(data.tags),
                "execution_mode": data.execution_mode,
                "reward_total": int(data.reward_total),
                "max_members": data.max_members,
                "status": TASK_STATUS_DRAFT,
                "publisher_id": actor.id,
                "visibility": data.visibility,
                "peak_id": data.peak_id,
                "deadline": data.deadline,
            }
        )
        await self._add_action(
            task=task,
            actor_id=actor.id,
            action="create",
            from_status=None,
            request_id=request_id,
        )
        response = task_to_dict(task, actor.display_name or actor.username)
        return await self._save(
            actor_id=actor.id,
            operation=_OP_CREATE,
            key=key,
            payload=payload,
            response=response,
        )

    async def update_task(
        self,
        *,
        actor: User,
        task_id: int,
        data: TaskUpdate,
        if_match: Optional[str],
        idempotency_key: Optional[str],
        request_id: Optional[str] = None,
    ) -> dict:
        payload = {"task_id": task_id, "if_match": if_match, **data.model_dump(mode="json", exclude_unset=True)}
        key, replay = await self._begin(
            actor_id=actor.id, operation=_OP_UPDATE, key=idempotency_key, payload=payload
        )
        if replay is not None:
            return replay

        task = await self.repo.get_for_update(task_id)
        if task is None:
            raise _task_not_found(task_id)
        if task.publisher_id != actor.id:
            raise AuthorizationException(
                message="只有发布者可以修改任务",
                error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
            )
        check_if_match(if_match, task.version)

        changes = data.model_dump(exclude_unset=True)
        if changes.get("deadline") is not None:
            require_future(changes["deadline"])

        if task.status in (TASK_STATUS_DRAFT, TASK_STATUS_REJECTED):
            allowed = set(changes)
        elif task.status == TASK_STATUS_PUBLISHED:
            allowed = _PUBLISHED_EDITABLE_FIELDS
        else:
            raise ConflictException(
                message="当前状态不可编辑，请先撤回或关闭任务",
                error_code=ErrorCode.Conflict.TASK_STATE_CONFLICT,
            )
        forbidden = set(changes) - allowed
        if forbidden:
            raise ConflictException(
                message="该状态下不可修改资金、范围或人数",
                error_code=ErrorCode.Conflict.TASK_STATE_CONFLICT,
                details={"fields": sorted(forbidden)},
            )

        if "reward_total" in changes:
            changes["reward_total"] = int(changes["reward_total"])
        if "execution_mode" in changes or "max_members" in changes:
            mode = changes.get("execution_mode", task.execution_mode)
            members = changes.get("max_members", task.max_members)
            if mode == EXECUTION_MODE_SINGLE and members != 1:
                raise ValidationException(
                    message="单人任务人数必须为 1",
                    error_code=ErrorCode.Validation.INVALID_TEAM_SIZE,
                )
            if mode == EXECUTION_MODE_TEAM and members < 2:
                raise ValidationException(
                    message="团队任务人数至少为 2",
                    error_code=ErrorCode.Validation.INVALID_TEAM_SIZE,
                )
        visibility = changes.get("visibility", task.visibility)
        peak_id = changes.get("peak_id", task.peak_id)
        if visibility == VISIBILITY_PEAK and not peak_id:
            raise ValidationException(message="峰内可见任务必须指定 peak_id")

        changes["version"] = task.version + 1
        await self.repo.update(task, changes)
        await self._add_action(
            task=task,
            actor_id=actor.id,
            action="update",
            from_status=task.status,
            request_id=request_id,
        )
        response = task_to_dict(task, actor.display_name or actor.username)
        return await self._save(
            actor_id=actor.id,
            operation=_OP_UPDATE,
            key=key,
            payload=payload,
            response=response,
        )

    async def request_review(
        self,
        *,
        actor: User,
        task_id: int,
        idempotency_key: Optional[str],
        request_id: Optional[str] = None,
    ) -> dict:
        payload = {"task_id": task_id}
        key, replay = await self._begin(
            actor_id=actor.id,
            operation=_OP_REVIEW_REQUEST,
            key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return replay
        task = await self.repo.get_for_update(task_id)
        if task is None:
            raise _task_not_found(task_id)
        if task.publisher_id != actor.id:
            raise AuthorizationException(
                message="只有发布者可以申请上架",
                error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
            )
        if task.status not in (TASK_STATUS_DRAFT, TASK_STATUS_REJECTED):
            raise ConflictException(
                message="只有草稿或驳回任务可以申请上架",
                error_code=ErrorCode.Conflict.TASK_STATE_CONFLICT,
            )
        require_future(task.deadline)
        previous = task.status
        await self.repo.update(
            task,
            {
                "status": TASK_STATUS_PENDING_REVIEW,
                "review_cycle": task.review_cycle + 1,
                "version": task.version + 1,
            },
        )
        await self._add_action(
            task=task,
            actor_id=actor.id,
            action="request_review",
            from_status=previous,
            request_id=request_id,
        )
        response = task_to_dict(task, await get_publisher_name(self.db, task.publisher_id))
        return await self._save(
            actor_id=actor.id,
            operation=_OP_REVIEW_REQUEST,
            key=key,
            payload=payload,
            response=response,
        )

    async def archive_task(
        self,
        *,
        actor: User,
        task_id: int,
        if_match: Optional[str],
        idempotency_key: Optional[str],
        request_id: Optional[str] = None,
    ) -> dict:
        payload = {"task_id": task_id, "if_match": if_match}
        key, replay = await self._begin(
            actor_id=actor.id, operation=_OP_ARCHIVE, key=idempotency_key, payload=payload
        )
        if replay is not None:
            return replay
        task = await self.repo.get_for_update(task_id)
        if task is None:
            raise _task_not_found(task_id)
        if task.publisher_id != actor.id and not actor.is_superuser:
            raise AuthorizationException(
                message="只有发布者可以归档任务",
                error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
            )
        check_if_match(if_match, task.version)
        if task.status not in (TASK_STATUS_DRAFT, TASK_STATUS_REJECTED):
            raise ConflictException(
                message="有资金或执行历史的非草稿任务只能关闭后归档",
                error_code=ErrorCode.Conflict.TASK_STATE_CONFLICT,
            )
        await self.repo.update(
            task, {"archived_at": now_utc(), "version": task.version + 1}
        )
        await self._add_action(
            task=task,
            actor_id=actor.id,
            action="archive",
            from_status=task.status,
            request_id=request_id,
        )
        response = task_to_dict(task)
        return await self._save(
            actor_id=actor.id,
            operation=_OP_ARCHIVE,
            key=key,
            payload=payload,
            response=response,
        )

    async def claim_task(
        self,
        *,
        actor: User,
        task_id: int,
        data: ClaimCreate,
        idempotency_key: Optional[str],
        request_id: Optional[str] = None,
    ) -> dict:
        payload = {"task_id": task_id, "team_id": data.team_id}
        key, replay = await self._begin(
            actor_id=actor.id, operation=_OP_CLAIM, key=idempotency_key, payload=payload
        )
        if replay is not None:
            return replay

        team = None
        if data.team_id is not None:
            team = await self.team_repo.get_team_for_update(data.team_id)
            if team is None or team.status == "archived":
                raise NotFoundException(
                    message="队伍不存在",
                    resource_type="team",
                    resource_id=data.team_id,
                )
            if team.captain_user_id != actor.id:
                raise AuthorizationException(
                    message="只有队长可以接取团队任务",
                    error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
                )

        task = await self.repo.get_for_update(task_id)
        if task is None:
            raise _task_not_found(task_id)
        if task.status != TASK_STATUS_PUBLISHED:
            raise ConflictException(
                message="任务当前不可接取",
                error_code=ErrorCode.Conflict.TASK_STATE_CONFLICT,
            )
        require_future(task.deadline, message="任务已过截止时间")
        if task.publisher_id == actor.id:
            raise AuthorizationException(
                message="发布者不能接取自己的任务",
                error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
            )
        await require_active_member(self.db, actor.id)

        if task.execution_mode == EXECUTION_MODE_TEAM:
            if data.team_id is None:
                raise ValidationException(
                    message="团队任务必须以队伍接取",
                    error_code=ErrorCode.Validation.INVALID_TEAM_SIZE,
                )
            await self._validate_team_roster(team, task, actor.id)
            member_ids = [member.user_id for member, _ in await self.team_repo.list_active_members(team.id)]
            leader_id = team.captain_user_id
        else:
            if data.team_id is not None:
                raise ValidationException(
                    message="单人任务不能以队伍接取",
                    error_code=ErrorCode.Validation.INVALID_TEAM_SIZE,
                )
            member_ids = [actor.id]
            leader_id = actor.id

        claim = await self.repo.create_claim(
            {
                "task_id": task.id,
                "team_id": data.team_id,
                "leader_user_id": leader_id,
                "status": "active",
            }
        )
        for user_id in member_ids:
            await self.repo.add_claim_member(claim.id, user_id, user_id == leader_id)

        previous = task.status
        await self.repo.update(
            task, {"status": TASK_STATUS_IN_PROGRESS, "version": task.version + 1}
        )
        if team is not None and team.status == "forming":
            await self.team_repo.update_team(team, {"status": "active"})
        await self._add_action(
            task=task,
            claim_id=claim.id,
            actor_id=actor.id,
            action="claim",
            from_status=previous,
            request_id=request_id,
        )
        members = await self.repo.list_claim_members(claim.id)
        response = claim_to_dict(claim, members, task=task)
        return await self._save(
            actor_id=actor.id,
            operation=_OP_CLAIM,
            key=key,
            payload=payload,
            response=response,
        )

    async def _validate_team_roster(self, team, task: Task, actor_id: int) -> None:
        if await self.team_repo.team_has_open_claim(team.id):
            raise ConflictException(
                message="该队伍已有进行中的任务",
                error_code=ErrorCode.Conflict.TEAM_ROSTER_LOCKED,
            )
        members = await self.team_repo.list_active_members(team.id)
        count = len(members)
        if count < 2 or count > task.max_members:
            raise ValidationException(
                message="队伍人数不符合任务要求",
                error_code=ErrorCode.Validation.INVALID_TEAM_SIZE,
                details={"count": count, "max_members": task.max_members},
            )
        for member, _user in members:
            if member.user_id == task.publisher_id:
                raise AuthorizationException(
                    message="发布者不能成为执行成员",
                    error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
                )
            profile = await require_active_member(self.db, member.user_id)
            if not can_view_task(task, member.user_id, profile):
                raise AuthorizationException(
                    message="队伍成员不满足任务可见范围",
                    error_code=ErrorCode.Authorization.SCOPE_FORBIDDEN,
                )

    async def cancel_claim(
        self,
        *,
        actor: User,
        claim_id: int,
        idempotency_key: Optional[str],
        request_id: Optional[str] = None,
    ) -> dict:
        payload = {"claim_id": claim_id}
        key, replay = await self._begin(
            actor_id=actor.id, operation=_OP_CANCEL, key=idempotency_key, payload=payload
        )
        if replay is not None:
            return replay
        claim = await self.repo.get_claim(claim_id)
        if claim is None:
            raise _claim_not_found(claim_id)
        task = await self.repo.get_for_update(claim.task_id)
        if task is None:
            raise _task_not_found(claim.task_id)
        claim = await self.repo.get_claim_for_update(claim_id)
        if claim is None:
            raise _claim_not_found(claim_id)
        if claim.leader_user_id != actor.id:
            raise AuthorizationException(
                message="只有队长可以取消执行",
                error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
            )
        if claim.status != "active":
            raise ConflictException(
                message="当前执行状态不可取消",
                error_code=ErrorCode.Conflict.TASK_STATE_CONFLICT,
            )
        previous = task.status
        settlement = None
        if task.deadline is not None and task.deadline <= now_utc():
            task_status = TASK_STATUS_EXPIRED
            await refund_reward(
                self.db,
                task=task,
                actor_id=actor.id,
                reason="执行取消且已过截止时间",
                request_id=request_id,
            )
            settlement = "refund"
        else:
            task_status = TASK_STATUS_PUBLISHED
        await self.repo.update_claim(
            claim,
            {"status": "cancelled", "version": claim.version + 1},
        )
        await self.repo.update(
            task,
            {
                "status": task_status,
                "closed_at": now_utc() if task_status == TASK_STATUS_EXPIRED else None,
                "version": task.version + 1,
            },
        )
        await self._add_action(
            task=task,
            claim_id=claim.id,
            actor_id=actor.id,
            action="cancel_claim",
            from_status=previous,
            request_id=request_id,
        )
        response = {
            "claim_id": claim.id,
            "task_status": task.status,
            "settlement": settlement,
        }
        return await self._save(
            actor_id=actor.id,
            operation=_OP_CANCEL,
            key=key,
            payload=payload,
            response=response,
        )

    async def submit_claim(
        self,
        *,
        actor: User,
        claim_id: int,
        data: SubmissionCreate,
        idempotency_key: Optional[str],
        request_id: Optional[str] = None,
    ) -> dict:
        payload = {"claim_id": claim_id, **data.model_dump(mode="json")}
        key, replay = await self._begin(
            actor_id=actor.id, operation=_OP_SUBMIT, key=idempotency_key, payload=payload
        )
        if replay is not None:
            return replay
        claim = await self.repo.get_claim(claim_id)
        if claim is None:
            raise _claim_not_found(claim_id)
        task = await self.repo.get_for_update(claim.task_id)
        if task is None:
            raise _task_not_found(claim.task_id)
        claim = await self.repo.get_claim_for_update(claim_id)
        if claim is None:
            raise _claim_not_found(claim_id)
        if claim.leader_user_id != actor.id:
            raise AuthorizationException(
                message="只有队长可以提交成果",
                error_code=ErrorCode.Authorization.ACCOUNT_ACCESS_DENIED,
            )
        if claim.status != "active":
            raise ConflictException(
                message="当前执行状态不可提交",
                error_code=ErrorCode.Conflict.TASK_STATE_CONFLICT,
            )
        if task.deadline is not None and task.deadline <= now_utc():
            raise ConflictException(
                message="任务已过截止时间，不能提交",
                error_code=ErrorCode.Conflict.TASK_STATE_CONFLICT,
            )
        revision = await self.repo.next_revision(claim.id)
        submission = await self.repo.create_submission(
            {
                "claim_id": claim.id,
                "revision": revision,
                "description": data.description,
                "attachments": list(data.attachments),
                "submitted_by": actor.id,
                "review_status": "pending",
            }
        )
        previous = task.status
        await self.repo.update_claim(
            claim,
            {
                "status": "submitted",
                "submitted_at": now_utc(),
                "version": claim.version + 1,
            },
        )
        await self.repo.update(
            task, {"status": TASK_STATUS_SUBMITTED, "version": task.version + 1}
        )
        await self._add_action(
            task=task,
            claim_id=claim.id,
            actor_id=actor.id,
            action="submit",
            from_status=previous,
            request_id=request_id,
        )
        members = await self.repo.list_claim_members(claim.id)
        response = claim_to_dict(claim, members, submission, task)
        return await self._save(
            actor_id=actor.id,
            operation=_OP_SUBMIT,
            key=key,
            payload=payload,
            response=response,
        )
