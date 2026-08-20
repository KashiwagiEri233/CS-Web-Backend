"""社区纯函数 / 映射工具（ER-15 Phase 0：从 community_service 提取，不改行为）。

- hash_ip_for_view / scan_mentions / generate_slug：无状态纯函数；
- to_author_summary：作者摘要映射（mask_email 脱敏）。

由各社区子服务（Post/Comment/Series 等）直接 import；community_service.py
已在 ER-15 Phase 4 删除（facade 收敛完毕），无 re-export 兼容负担。
"""

import hashlib
import hmac
import re
import unicodedata

from app.core.config import settings
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import COMMUNITY_LIMITS, MENTION_PATTERN
from app.models.user import User
from app.utils.mask import mask_email


def hash_ip_for_view(ip: str) -> str:
    """匿名化访客 IP 用于浏览去重计数。

    密钥来自 COMMUNITY_IP_HASH_SECRET（强制从环境读取，缺失即 fail-fast）。
    绝不使用硬编码常量——否则匿名化对掌握源码者可逆。
    """
    secret = settings.COMMUNITY_IP_HASH_SECRET
    if not secret:
        raise RuntimeError(
            "COMMUNITY_IP_HASH_SECRET 未配置：拒绝处理访客 IP 匿名化"
        )
    return hmac.new(secret.encode(), ip.encode(), hashlib.sha256).hexdigest()


def scan_mentions(content: str) -> list[str]:
    return list(dict.fromkeys(re.findall(MENTION_PATTERN, content)))


def generate_slug(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[: COMMUNITY_LIMITS["SLUG_MAX"]].strip("-") or "post"


def to_author_summary(user) -> dict:
    return {
        "id": user.id,
        "email": mask_email(user.email) or "",
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "avatar_type": user.avatar_type or "initial",
    }


async def load_users_by_ids(db: AsyncSession, ids: Iterable[int]) -> dict[int, User]:
    """批量加载用户（id → User）。重复实现治理波次 B2b：收敛 post/comment 作者补齐重复。"""
    id_set = {i for i in ids if i}
    if not id_set:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(id_set)))).scalars().all()
    return {u.id: u for u in rows}
