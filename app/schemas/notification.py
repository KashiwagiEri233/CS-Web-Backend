"""站内通知 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.base import TZModel

NOTIFICATION_TYPES = {"system", "admin", "activity"}


class NotificationOut(TZModel):
    """通知出参。"""

    id: int
    user_id: int
    type: str
    title: str
    content: Optional[str] = None
    is_read: bool
    sender_id: Optional[int] = None
    created_at: datetime


class BroadcastRequest(BaseModel):
    """管理员全站通知。"""

    title: str
    content: Optional[str] = None
    # 定向用户列表；为空 = 广播给全部用户
    user_ids: Optional[list[int]] = None
