"""学习助手 API：LLM 对话（SSE 流式）+ 会话管理 + Skills 工具调用。

契约基线（openapi.baseline.json）：
- POST /api/v1/auxilio/chat                     SSE 流式对话（conversation_id + messages）
- GET  /api/v1/auxilio/conversations            当前用户会话列表
- GET  /api/v1/auxilio/conversations/{id}/messages  会话历史
- GET  /api/v1/tools/auxilio                    薄弱点分析（挂 /tools 前缀，由 analysis_router 提供）

2026-08-17 恢复：此前提交 4b09a9d 精简为 chat/path/recommend 并改挂 /tools 前缀，
与基线契约及前端 BFF（/auxilio/*）脱节；path/recommend 调用的 service 方法亦不存在。
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.core.loguru_logger import get_logger
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    ValidationException,
)
from app.database import get_db
from app.dependencies import get_current_active_user
from app.dependencies_services import get_auxilio_service
from app.models.conversation import AgentRun, ChatEvent, ChatMessage, Conversation
from app.models.learning import WrongAnswer
from app.models.llm_usage import LlmUsageLog
from app.models.user import User
from app.services import auxilio_agent
from app.services.auxilio_service import AuxilioService

router = APIRouter(prefix="/auxilio", tags=["学习助手"])
logger = get_logger("auxilio.api")


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    conversation_id: Optional[int] = None
    messages: list[ChatTurn] = Field(min_length=1, max_length=40)
    #: Agent 预设（AGENT_PRESETS 键，如 exam_sprint / web_research）；缺省服务端按消息启发式匹配
    preset_id: Optional[str] = None


class ForkRequest(BaseModel):
    from_message_id: Optional[int] = None
    title: Optional[str] = Field(default=None, max_length=200)


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _own_conversation(
    db: AsyncSession, user: User, conversation_id: int
) -> Conversation:
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user.id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise NotFoundException(
            resource_type="学习助手会话", resource_id=conversation_id
        )
    return conv


@router.post("/chat")
async def chat(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    service: AuxilioService = Depends(get_auxilio_service),
):
    """SSE 流式对话：支持 OpenAI / Anthropic 双协议与 Skills 工具调用。"""
    last = req.messages[-1]
    content = last.content if last.role == "user" else ""
    input_message_id: int | None = None
    if req.conversation_id is not None:
        conv = await _own_conversation(db, user, req.conversation_id)
        if conv.archived_at is not None:
            raise ConflictException(message="已归档会话不可继续对话，请先取消归档")
        input_message_id = await service.append_user_message(conv.id, content)
    else:
        conv = await service.create_conversation_with_user_msg(user.id, content)
        input_message = (
            await db.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == conv.id, ChatMessage.role == "user"
                )
                .order_by(ChatMessage.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        input_message_id = input_message.id if input_message else None
    run = await service.create_agent_run(
        user_id=user.id,
        conversation_id=conv.id,
        input_message_id=input_message_id,
        preset_id=req.preset_id,
    )

    history = [{"role": m.role, "content": m.content} for m in req.messages]

    async def event_stream():
        assistant_text: list[str] = []
        tool_records: list[dict] = []
        new_title: Optional[str] = None
        usage: Optional[dict] = None
        event_seq = 0  # Trajectory 事件序号（对话内自增）
        run_status = "completed"
        run_error: Optional[str] = None
        # 用户级 Trajectory 开关（llm_configs.trajectory_enabled；默认开）
        trajectory_on = True
        try:
            trajectory_on = await auxilio_agent.user_feature_flag(
                db, user.id, "trajectory_enabled"
            )
        except Exception:  # noqa: BLE001 - 开关读取失败按默认开处理
            trajectory_on = True
        started = now_utc()
        try:
            yield sse(
                {"type": "conversation", "conversationId": conv.id, "runId": run.id}
            )
            async for ev in auxilio_agent.run_chat(
                db, user, history, preset_id=req.preset_id
            ):
                # Trajectory 事件落库（融合点 2，append-only，best-effort 不影响对话）
                if trajectory_on:
                    event_seq += 1
                    try:
                        db.add(
                            ChatEvent(
                                conversation_id=conv.id,
                                run_id=run.id,
                                user_id=user.id,
                                seq=event_seq,
                                event_type=str(ev.get("type", "")),
                                payload=ev,
                            )
                        )
                        await db.commit()
                    except Exception as exc:  # noqa: BLE001 - 事件落库失败不影响对话
                        await db.rollback()
                        logger.warning(
                            "Chat event persistence failed",
                            run_id=run.id,
                            seq=event_seq,
                            error_type=type(exc).__name__,
                        )
                if ev.get("type") == "delta":
                    assistant_text.append(ev.get("text", ""))
                elif ev.get("type") == "tool_call":
                    tool_records.append(
                        {
                            "name": ev.get("name", ""),
                            "arguments": ev.get("arguments", "{}"),
                        }
                    )
                elif ev.get("type") == "usage":
                    usage = ev
                elif ev.get("type") == "done":
                    new_title = ev.get("title")
                elif ev.get("type") == "error":
                    run_status = "failed"
                    run_error = str(ev.get("message") or "Agent 执行失败")
                yield sse(ev)
        except asyncio.CancelledError:
            run_status = "cancelled"
            run_error = "客户端中断流式连接"
            raise
        except Exception as exc:  # noqa: BLE001 - 流式中途异常也要给出结束事件
            run_status = "failed"
            run_error = str(exc)
            yield sse({"type": "error", "message": str(exc)})
        finally:
            # LLM 用量落库（token 计量，供工作台统计与学习助手 Skill 查询）
            if usage:
                try:
                    db.add(
                        LlmUsageLog(
                            user_id=user.id,
                            provider=usage.get("provider") or "openai",
                            model=usage.get("model") or "unknown",
                            prompt_tokens=usage.get("prompt_tokens") or 0,
                            completion_tokens=usage.get("completion_tokens") or 0,
                            total_tokens=usage.get("total_tokens") or 0,
                            latency_ms=int(
                                (now_utc() - started).total_seconds() * 1000
                            ),
                        )
                    )
                    await db.commit()
                except Exception as exc:  # noqa: BLE001 - 用量记录失败不影响对话
                    await db.rollback()
                    logger.warning(
                        "LLM usage persistence failed",
                        run_id=run.id,
                        error_type=type(exc).__name__,
                    )
            # 持久化助手消息 + 会话标题（提取到服务层；LlmUsageLog 依 §14.3 例外保留在路由）
            output_message_id = await service.persist_assistant_message(
                conv, assistant_text, tool_records, new_title
            )
            if assistant_text and output_message_id is None:
                run_status = "failed"
                run_error = run_error or "助手消息持久化失败"
            await service.finish_agent_run(
                run,
                status=run_status,
                output_message_id=output_message_id,
                usage=usage,
                error_message=run_error,
                started_at=started,
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations")
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    limit: int = 20,
    include_archived: bool = False,
):
    conditions = [
        Conversation.user_id == user.id,
        Conversation.deleted_at.is_(None),
    ]
    if not include_archived:
        conditions.append(Conversation.archived_at.is_(None))
    rows = (
        (
            await db.execute(
                select(Conversation)
                .where(*conditions)
                .order_by(Conversation.updated_at.desc())
                .limit(min(limit, 50))
            )
        )
        .scalars()
        .all()
    )
    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "parentConversationId": c.parent_conversation_id,
                "rootConversationId": c.root_conversation_id or c.id,
                "forkedFromMessageId": c.forked_from_message_id,
                "archivedAt": c.archived_at.isoformat() if c.archived_at else None,
                "createdAt": c.created_at.isoformat() if c.created_at else None,
                "updatedAt": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in rows
        ]
    }


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    await _own_conversation(db, user, conversation_id)
    rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "toolCalls": m.tool_calls or [],
                "createdAt": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ]
    }


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ArchiveRequest(BaseModel):
    archived: bool = True


class MistakeUpdateRequest(BaseModel):
    status: str = Field(pattern="^(new|reviewing|mastered)$")
    error_reason: Optional[str] = Field(default=None, max_length=1000)


class MistakeReviewRequest(BaseModel):
    feedback: str = Field(pattern="^(again|hard|good|easy)$")
    error_reason: Optional[str] = Field(default=None, max_length=1000)


class LearningGoalCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    exam_id: Optional[int] = None
    description: Optional[str] = Field(default=None, max_length=2000)
    target_date: Optional[datetime] = None
    weekly_budget_minutes: int = Field(default=300, ge=15, le=10080)
    preferred_slots: list[str] = Field(default_factory=list, max_length=14)


class LearningGoalUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    exam_id: Optional[int] = None
    description: Optional[str] = Field(default=None, max_length=2000)
    target_date: Optional[datetime] = None
    weekly_budget_minutes: Optional[int] = Field(default=None, ge=15, le=10080)
    preferred_slots: Optional[list[str]] = Field(default=None, max_length=14)
    status: Optional[str] = Field(default=None, pattern="^(active|paused|completed)$")


class LearningPlanUpdateRequest(BaseModel):
    status: Optional[str] = Field(
        default=None, pattern="^(planned|completed|deferred|skipped)$"
    )
    locked: Optional[bool] = None
    defer_to: Optional[date] = None


def _learning_goal_out(goal) -> dict:
    return {
        "id": goal.id,
        "examId": goal.exam_id,
        "title": goal.title,
        "description": goal.description,
        "targetDate": goal.target_date.isoformat() if goal.target_date else None,
        "weeklyBudgetMinutes": goal.weekly_budget_minutes,
        "preferredSlots": goal.preferred_slots or [],
        "status": goal.status,
        "createdAt": goal.created_at.isoformat() if goal.created_at else None,
        "updatedAt": goal.updated_at.isoformat() if goal.updated_at else None,
    }


def _learning_plan_item_out(item) -> dict:
    return {
        "id": item.id,
        "goalId": item.goal_id,
        "planDate": item.plan_date.isoformat(),
        "sourceType": item.source_type,
        "sourceKey": item.source_key,
        "title": item.title,
        "rationale": item.rationale,
        "estimatedMinutes": item.estimated_minutes,
        "status": item.status,
        "locked": item.locked,
        "metadata": item.metadata_json or {},
        "completedAt": item.completed_at.isoformat() if item.completed_at else None,
    }


@router.patch("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: int,
    req: RenameRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    service: AuxilioService = Depends(get_auxilio_service),
):
    conversation = await _own_conversation(db, user, conversation_id)
    try:
        await service.rename_conversation(conversation, req.title)
    except ValueError as exc:
        raise ValidationException(message=str(exc)) from exc
    return {"conversation": {"id": conversation.id, "title": conversation.title}}


@router.post("/conversations/{conversation_id}/archive")
async def archive_conversation(
    conversation_id: int,
    req: ArchiveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    service: AuxilioService = Depends(get_auxilio_service),
):
    conversation = await _own_conversation(db, user, conversation_id)
    await service.set_conversation_archived(conversation, req.archived)
    return {
        "conversation": {
            "id": conversation.id,
            "archivedAt": (
                conversation.archived_at.isoformat()
                if conversation.archived_at
                else None
            ),
        }
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    cascade: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    service: AuxilioService = Depends(get_auxilio_service),
):
    conversation = await _own_conversation(db, user, conversation_id)
    try:
        deleted_count = await service.delete_conversation(conversation, cascade=cascade)
    except ValueError as exc:
        raise ConflictException(message=str(exc)) from exc
    return {"deleted": True, "deletedConversationCount": deleted_count}


@router.get("/mistakes")
async def list_mistakes(
    status: Optional[str] = None,
    tag: Optional[str] = None,
    due_only: bool = False,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """返回当前用户错题快照；过滤在服务边界内完成所有权隔离。"""
    conditions = [WrongAnswer.user_id == user.id]
    if status:
        conditions.append(WrongAnswer.status == status)
    if due_only:
        conditions.append(WrongAnswer.review_due_at <= now_utc())
    query = (
        select(WrongAnswer)
        .where(*conditions)
        .order_by(WrongAnswer.review_due_at.asc(), WrongAnswer.id.asc())
    )
    rows = list((await db.execute(query.limit(min(limit, 100)))).scalars().all())
    if tag:
        rows = [row for row in rows if tag in (row.knowledge_tags or [])]
    return {
        "mistakes": [
            {
                "id": row.id,
                "examId": row.exam_id,
                "questionId": row.question_id,
                "question": row.question_snapshot or {},
                "knowledgeTags": row.knowledge_tags or [],
                "latestAnswer": row.latest_answer,
                "correctAnswer": row.correct_answer,
                "errorReason": row.error_reason,
                "mistakeCount": row.mistake_count,
                "reviewStreak": row.review_streak,
                "status": row.status,
                "reviewDueAt": (
                    row.review_due_at.isoformat() if row.review_due_at else None
                ),
                "lastWrongAt": (
                    row.last_wrong_at.isoformat() if row.last_wrong_at else None
                ),
                "lastReviewedAt": (
                    row.last_reviewed_at.isoformat() if row.last_reviewed_at else None
                ),
            }
            for row in rows
        ]
    }


@router.patch("/mistakes/{mistake_id}")
async def update_mistake(
    mistake_id: int,
    req: MistakeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    row = (
        await db.execute(
            select(WrongAnswer).where(
                WrongAnswer.id == mistake_id, WrongAnswer.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundException(resource_type="错题", resource_id=mistake_id)
    row.status = req.status
    if req.error_reason is not None:
        row.error_reason = req.error_reason.strip() or None
    row.last_reviewed_at = now_utc()
    if req.status == "mastered":
        row.review_due_at = now_utc()
    await db.commit()
    return {
        "mistake": {"id": row.id, "status": row.status, "errorReason": row.error_reason}
    }


@router.post("/mistakes/{mistake_id}/review")
async def review_mistake(
    mistake_id: int,
    req: MistakeReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    service: AuxilioService = Depends(get_auxilio_service),
):
    try:
        row = await service.review_wrong_answer(
            user.id,
            mistake_id,
            req.feedback,
            req.error_reason,
        )
    except LookupError as exc:
        raise NotFoundException(resource_type="错题", resource_id=mistake_id) from exc
    except ValueError as exc:
        raise ValidationException(message=str(exc)) from exc
    return {
        "mistake": {
            "id": row.id,
            "status": row.status,
            "reviewStreak": row.review_streak,
            "reviewDueAt": row.review_due_at.isoformat() if row.review_due_at else None,
            "lastReviewedAt": (
                row.last_reviewed_at.isoformat() if row.last_reviewed_at else None
            ),
        }
    }


@router.get("/goals")
async def list_learning_goals(
    include_completed: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    service: AuxilioService = Depends(get_auxilio_service),
):
    goals = await service.list_learning_goals(
        user.id, include_completed=include_completed
    )
    return {"goals": [_learning_goal_out(goal) for goal in goals]}


@router.post("/goals", status_code=201)
async def create_learning_goal(
    req: LearningGoalCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    service: AuxilioService = Depends(get_auxilio_service),
):
    try:
        goal = await service.create_learning_goal(
            user.id,
            title=req.title,
            exam_id=req.exam_id,
            description=req.description,
            target_date=req.target_date,
            weekly_budget_minutes=req.weekly_budget_minutes,
            preferred_slots=req.preferred_slots,
        )
    except ValueError as exc:
        raise ValidationException(message=str(exc)) from exc
    return {"goal": _learning_goal_out(goal)}


@router.patch("/goals/{goal_id}")
async def update_learning_goal(
    goal_id: int,
    req: LearningGoalUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    service: AuxilioService = Depends(get_auxilio_service),
):
    changes = req.model_dump(exclude_unset=True)
    try:
        goal = await service.update_learning_goal(user.id, goal_id, **changes)
    except LookupError as exc:
        raise NotFoundException(resource_type="学习目标", resource_id=goal_id) from exc
    except ValueError as exc:
        raise ValidationException(message=str(exc)) from exc
    return {"goal": _learning_goal_out(goal)}


@router.delete("/goals/{goal_id}")
async def delete_learning_goal(
    goal_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    service: AuxilioService = Depends(get_auxilio_service),
):
    try:
        await service.delete_learning_goal(user.id, goal_id)
    except LookupError as exc:
        raise NotFoundException(resource_type="学习目标", resource_id=goal_id) from exc
    return {"deleted": True}


@router.get("/plan")
async def list_learning_plan(
    plan_date: Optional[date] = None,
    generate: bool = True,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    service: AuxilioService = Depends(get_auxilio_service),
):
    target_date = plan_date or date.today()
    items = await service.list_learning_plan(user.id, target_date, generate=generate)
    return {
        "planDate": target_date.isoformat(),
        "items": [_learning_plan_item_out(item) for item in items],
    }


@router.patch("/plan/{item_id}")
async def update_learning_plan(
    item_id: int,
    req: LearningPlanUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    service: AuxilioService = Depends(get_auxilio_service),
):
    try:
        item = await service.update_learning_plan_item(
            user.id,
            item_id,
            status=req.status,
            locked=req.locked,
            defer_to=req.defer_to,
        )
    except LookupError as exc:
        raise NotFoundException(
            resource_type="学习计划项", resource_id=item_id
        ) from exc
    except ValueError as exc:
        raise ValidationException(message=str(exc)) from exc
    return {"item": _learning_plan_item_out(item)}


@router.post("/conversations/{conversation_id}/fork")
async def fork_conversation(
    conversation_id: int,
    req: ForkRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    service: AuxilioService = Depends(get_auxilio_service),
):
    """从当前用户会话的某条消息创建独立分支。"""
    source = await _own_conversation(db, user, conversation_id)
    try:
        branch, copied_count = await service.fork_conversation(
            source, from_message_id=req.from_message_id, title=req.title
        )
    except ValueError as exc:
        raise ValidationException(message=str(exc)) from exc
    return {
        "conversation": {
            "id": branch.id,
            "title": branch.title,
            "parentConversationId": branch.parent_conversation_id,
            "rootConversationId": branch.root_conversation_id or branch.id,
            "forkedFromMessageId": branch.forked_from_message_id,
            "copiedMessageCount": copied_count,
        }
    }


@router.get("/conversations/{conversation_id}/events")
async def list_events(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Trajectory 事件回放（融合点 2 的消费端）：按 seq 返回会话全事件流。"""
    await _own_conversation(db, user, conversation_id)
    rows = (
        (
            await db.execute(
                select(ChatEvent)
                .where(ChatEvent.conversation_id == conversation_id)
                .order_by(ChatEvent.created_at.asc(), ChatEvent.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "events": [
            {
                "id": e.id,
                "seq": e.seq,
                "runId": e.run_id,
                "eventType": e.event_type,
                "payload": e.payload or {},
                "createdAt": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ]
    }


@router.get("/conversations/{conversation_id}/runs")
async def list_runs(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """返回会话每轮 Agent 执行的状态、成本和消息关联。"""
    await _own_conversation(db, user, conversation_id)
    rows = list(
        (
            await db.execute(
                select(AgentRun)
                .where(AgentRun.conversation_id == conversation_id)
                .order_by(AgentRun.created_at.asc(), AgentRun.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "runs": [
            {
                "id": run.id,
                "triggerType": run.trigger_type,
                "presetId": run.preset_id,
                "status": run.status,
                "inputMessageId": run.input_message_id,
                "outputMessageId": run.output_message_id,
                "promptTokens": run.prompt_tokens,
                "completionTokens": run.completion_tokens,
                "totalTokens": run.total_tokens,
                "latencyMs": run.latency_ms,
                "errorCode": run.error_code,
                "errorMessage": run.error_message,
                "startedAt": run.started_at.isoformat() if run.started_at else None,
                "completedAt": (
                    run.completed_at.isoformat() if run.completed_at else None
                ),
            }
            for run in rows
        ]
    }


# ---------------------------------------------------------------------------
# 薄弱点分析（契约：GET /api/v1/tools/auxilio，挂 /tools 前缀）
# ---------------------------------------------------------------------------

analysis_router = APIRouter(tags=["学习助手"])


@analysis_router.get("/auxilio")
async def auxilio_analysis(
    service: AuxilioService = Depends(get_auxilio_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    return await service.analyze_learning_profile(current_user.id)
