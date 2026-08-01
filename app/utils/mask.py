"""数据脱敏工具：邮箱/手机号掩码（跨层纯工具，与前端 mask.ts 语义对齐）。"""

from __future__ import annotations

import re

_EMAIL_LOCAL_RE = re.compile(r"^(.{0,2}).*")


def mask_email(email: str | None) -> str | None:
    """邮箱脱敏：保留前 2 字符与域名，中间用 *** 替代。

    例：alice@example.com → al***@example.com
    """
    if not email:
        return None
    if "@" not in email:
        return email
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        return f"{local}***@{domain}"
    return f"{local[:2]}***@{domain}"


def mask_phone(phone: str | None) -> str | None:
    """手机号脱敏：保留前 3 后 4。"""
    if not phone:
        return None
    if len(phone) <= 7:
        return f"{phone[:3]}***"
    return f"{phone[:3]}***{phone[-4:]}"
