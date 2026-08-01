"""图片文件魔数校验（跨层纯工具，无 DB/Request 依赖）。

与前端语义对齐（src/shared/utils/image-utils.ts）：检查文件头字节，
拒绝「扩展名/Content-Type 与内容不符」的文件。
"""

from __future__ import annotations

# 各格式魔数（与前端一致）
_MAGIC_BYTES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF", b"WEBP"),  # RIFF....WEBP（WebP 头在偏移 8）
    "image/gif": (b"GIF87a", b"GIF89a"),
}


def sniff_mime(data: bytes) -> str | None:
    """根据文件头嗅探真实 MIME；无法识别返回 None。"""
    if len(data) < 16:
        return None
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    return None


def is_valid_image_mime(data: bytes, declared_mime: str) -> bool:
    """校验文件内容是否匹配声明的 MIME 类型。"""
    actual = sniff_mime(data)
    if actual is None:
        return False
    if declared_mime in _MAGIC_BYTES:
        return actual == declared_mime
    # 声明类型不在白名单：按内容判定（不允许任意类型冒充）
    return False
