"""学习助手 API：LLM 对话（SSE 流式）+ 会话管理 + Skills 工具调用。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_active_user
from app.dependencies import get_db
from app.models.conversation import ChatMessage, Conversation
from app.models.llm_usage import LlmUsageLog
from app.models.user import User
from app.services import auxilio_agent

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
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user)):
    """SSE 流式对话：支持 OpenAI / Anthropic 双协议与 Skills 工具调用。"""
    if req.conversation_id is not None:
        conv = await _own_conversation(db, user, req.conversation_id)
    else:
        conv = Conversation(user_id=user.id, title="新会话")
        db.add(conv)
        await db.flush()

    # 持久化用户消息
    user_msg = ChatMessage(
        conversation_id=conv.id,
        role="user",
        content=req.messages[-1].content if req.messages[-1].role == "user" else "",
    )
    db.add(user_msg)
    await db.commit()

    history = [{"role": m.role, "content": m.content} for m in req.messages]

    async def event_stream():
        assistant_text: list[str] = []
        tool_records: list[dict] = []
        new_title: Optional[str] = None
        usage: Optional[dict] = None
        started = datetime.utcnow()
        try:
            async for ev in auxilio_agent.run_chat(db, user, history):
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
                            latency_ms=int((datetime.utcnow() - started).total_seconds() * 1000),
                        )
                    )
                    await db.commit()
                except Exception:  # noqa: BLE001 - 用量记录失败不影响对话
                    pass
            # 持久化助手消息 + 会话标题
            try:
                async with db.begin():
                    if new_title and conv.title == "新会话":
                        conv.title = new_title
                        conv.updated_at = datetime.utcnow()
                    if assistant_text:
                        db.add(
                            ChatMessage(
                                conversation_id=conv.id,
                                role="assistant",
                                content="".join(assistant_text),
                                tool_calls=tool_records or None,
                            )
                        )
                    conv.updated_at = datetime.utcnow()
            except Exception:  # noqa: BLE001 - 持久化失败不影响已输出内容
                pass

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
