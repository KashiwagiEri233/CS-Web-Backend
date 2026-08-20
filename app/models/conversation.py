"""学习助手会话模型：conversations / messages。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime as _DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import now_utc
from app.database import Base
from app.models.types import JSONDict

DateTime = _DateTime(timezone=True)


class Conversation(Base):
    """一次学习助手会话（含历史消息）。"""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新会话")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_utc, onupdate=now_utc
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, title='{self.title}')>"


class ChatMessage(Base):
    """会话内消息：user / assistant / tool 事件记录。"""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 该条 assistant 消息触发的工具调用记录 [{name, arguments}]
    tool_calls: Mapped[Optional[list]] = mapped_column(
        JSONDict, nullable=True, default=list
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    def __repr__(self) -> str:
        return f"<ChatMessage({self.role}, conv={self.conversation_id})>"


class ChatEvent(Base):
    """会话全事件流（Trajectory 日志，append-only，融合点 2）。

    记录对话过程中模型看到/产出的一切：delta / tool_call / tool_result / usage /
    done / error。`chat_messages` 保留为对外快照，本表用于回放与调试。
    """

    __tablename__ = "chat_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    #: 会话内事件序号（从 1 起，单次对话单生成者，进程内自增）
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    #: delta / tool_call / tool_result / usage / done / error
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    #: 事件体（文本 / 工具名与参数 / 用量 / 标题 / 错误信息）
    payload: Mapped[Optional[dict]] = mapped_column(JSONDict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_chat_events_conv_seq"),
    )

    def __repr__(self) -> str:
        return (
            f"<ChatEvent(conv={self.conversation_id}, seq={self.seq}, "
            f"{self.event_type})>"
        )
