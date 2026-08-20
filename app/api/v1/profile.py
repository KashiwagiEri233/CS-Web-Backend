"""个人资料 API：资料 CRUD / 头像 / 改密 / 公开主页。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse

from app.core.exceptions import NotFoundException
from app.core.request_context import get_client_meta
from app.dependencies import get_current_active_user
from app.dependencies_services import get_auth_service, get_user_service
from app.models.user import User
from app.schemas.auth import UserOut
from app.schemas.profile import (
    AvatarPresetRequest,
    ChangePasswordRequest,
    ProfileResponse,
    ProfileUpdate,
    PublicUserProfileResponse,
)
from app.services.auth.auth_service import AuthService
from app.services.user.user_service import UserService

router = APIRouter()

# 头像上传限制（与前端一致）
AVATAR_MAX_SIZE = 2 * 1024 * 1024
AVATAR_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
AVATAR_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
AVATAR_FILENAME_RE = re.compile(
    r"^(?:user\d+|[a-f0-9-]{36})-\d+\.(jpg|jpeg|png|webp|gif)$", re.IGNORECASE
)

# 数据目录（相对仓库根；与前端 data/ 语义一致，未来可切换对象存储）
DATA_DIR = Path("data")
AVATARS_DIR = DATA_DIR / "avatars"


def _avatar_path(filename: str) -> Path:
    return AVATARS_DIR / filename


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """获取当前用户完整资料（含活动参与记录）。"""
    return await user_service.get_profile(current_user.id)


@router.put("/profile", response_model=UserOut)
async def update_profile(
    body: ProfileUpdate,
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """更新个人资料（displayName/bio/githubUrl/websiteUrl/techTags）。"""
    return await user_service.update_profile_fields(current_user.id, body)


@router.post("/profile/password")
async def change_password(
    body: ChangePasswordRequest,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """修改密码：旧密码校验 → 历史复用检测 → 重哈希 + 全端登出。"""
    await auth_service.change_password(
        current_user.id, body.old_password, body.new_password
    )
    return {"ok": True}


@router.post("/profile/avatar/preset", response_model=UserOut)
async def set_preset_avatar(
    body: AvatarPresetRequest,
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """设置预设头像（avatar_type=preset）。"""
    return await user_service.set_preset_avatar(current_user.id, body.preset_id)


@router.post("/profile/avatar/upload", response_model=UserOut)
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    user_service: UserService = Depends(get_user_service),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """上传自定义头像（≤2MB，JPEG/PNG/WebP/GIF，魔数校验）。"""
    content = await file.read()
    return await user_service.save_uploaded_avatar(
        current_user.id,
        content,
        file.content_type or "",
        file.filename or "",
        client_meta=get_client_meta(request),
    )


@router.get("/avatars/{filename}")
async def serve_avatar(filename: str) -> Any:
    """头像静态服务（公开）。文件名严格校验防路径遍历。"""
    if not AVATAR_FILENAME_RE.match(filename):
        raise NotFoundException(
            message="头像不存在", resource_type="avatar", resource_id=filename
        )
    path = _avatar_path(filename)
    if not path.is_file():
        raise NotFoundException(
            message="头像不存在", resource_type="avatar", resource_id=filename
        )
    ext = path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    return FileResponse(path, media_type=mime_map.get(ext, "application/octet-stream"))


@router.get("/users/{user_id}", response_model=PublicUserProfileResponse)
async def get_public_user(
    user_id: int,
    user_service: UserService = Depends(get_user_service),
) -> Any:
    """用户公开主页（无需登录）：公开资料 + 社区/考试统计。"""
    profile = await user_service.get_public_profile(user_id)
    if profile is None:
        raise NotFoundException(
            message="用户不存在", resource_type="user", resource_id=str(user_id)
        )
    return profile
