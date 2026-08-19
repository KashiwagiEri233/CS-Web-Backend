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

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.database import get_db
from app.dependencies import get_current_active_user
from app.dependencies_services import get_auxilio_service
from app.models.conversation import ChatEvent, ChatMessage, Conversation
from app.models.llm_usage import LlmUsageLog
from app.models.user import User
from app.services import auxilio_agent
from app.services.auxilio_service import AuxilioService

router = APIRouter(prefix="/auxilio", tags=["学习助手"])


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    conversation_id: Optional[int] = None
    messages: list[ChatTurn] = Field(min_length=1, max_length=40)


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _own_conversation(db: AsyncSession, user: User, conversation_id: int) -> Conversation:
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
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
    if req.conversation_id is not None:
        conv = await _own_conversation(db, user, req.conversation_id)
        await service.append_user_message(conv.id, content)
    else:
        conv = await service.create_conversation_with_user_msg(user.id, content)

    history = [{"role": m.role, "content": m.content} for m in req.messages]

    async def event_stream():
        assistant_text: list[str] = []
        tool_records: list[dict] = []
        new_title: Optional[str] = None
        usage: Optional[dict] = None
        event_seq = 0  # Trajectory 事件序号（对话内自增）
        started = now_utc()
        try:
            async for ev in auxilio_agent.run_chat(db, user, history):
                # Trajectory 事件落库（融合点 2，append-only，best-effort 不影响对话）
                event_seq += 1
                try:
                    db.add(
                        ChatEvent(
                            conversation_id=conv.id,
                            user_id=user.id,
                            seq=event_seq,
                            event_type=str(ev.get("type", "")),
                            payload=ev,
                        )
                    )
                    await db.commit()
                except Exception:  # noqa: BLE001 - 事件落库失败不影响对话
                    await db.rollback()
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
                yield sse(ev)
        except Exception as exc:  # noqa: BLE001 - 流式中途异常也要给出结束事件
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
                            latency_ms=int((now_utc() - started).total_seconds() * 1000),
                        )
                    )
                    await db.commit()
                except Exception:  # noqa: BLE001 - 用量记录失败不影响对话
                    pass
            # 持久化助手消息 + 会话标题（提取到服务层；LlmUsageLog 依 §14.3 例外保留在路由）
            await service.persist_assistant_message(
                conv, assistant_text, tool_records, new_title
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
):
    rows = (
        await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
            .limit(min(limit, 50))
        )
    ).scalars().all()
    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
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
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        )
    ).scalars().all()
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
