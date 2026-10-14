"""个人资料服务：资料字段 / 头像（预设+上传）/ 公开主页。

C-17 拆分第一切片：从 user_service.py 抽出。profile 域与自我 CRUD、
管理员操作零内部方法交叉，仅通过组合 UserService 委托 get_user
（含 NotFound 语义）避免重复实现。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ErrorCode, ValidationException
from app.core.timezone import now_utc
from app.models.user import User
from app.repositories.activity_participation_repo import ActivityParticipationRepository
from app.repositories.user_repo import UserRepository
from app.schemas.profile import ProfileUpdate
from app.services.user.user_service import UserService
from app.utils.image_validate import is_valid_image_mime

# 预设头像（与前端 src/shared/config/avatar-presets.ts 对齐；文件由前端静态服务）
_PRESET_AVATAR_URL = "/avatars/presets/preset-{id}.svg"
_PRESET_COUNT = 6

# 头像上传限制（与前端一致）
AVATAR_MAX_SIZE = 2 * 1024 * 1024
AVATAR_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
AVATAR_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

_DATA_DIR = Path("data")
_AVATARS_DIR = _DATA_DIR / "avatars"


class ProfileService:
    """个人资料服务（资料字段 / 头像 / 公开主页）。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.activity_repo = ActivityParticipationRepository(db)
        # 组合 UserService 委托 get_user（含 NotFound 语义），避免复制查询逻辑
        self.user_service = UserService(db)

    async def get_profile(self, user_id: int) -> dict:
        """当前用户完整资料：用户 + 活动参与记录。"""
        user = await self.user_service.get_user(user_id)
        activities = await self.activity_repo.list_for_user(user_id)
        return {"user": user, "activities": activities}

    async def update_profile_fields(self, user_id: int, update: ProfileUpdate) -> User:
        """更新个人资料业务字段（display_name/bio/github_url/website_url/tech_tags）。"""
        user = await self.user_service.get_user(user_id)

        data = update.model_dump(exclude_unset=True)
        sets: dict = {}
        if "display_name" in data:
            sets["display_name"] = data["display_name"]
        if "bio" in data:
            sets["bio"] = data["bio"]
        if "github_url" in data:
            sets["github_url"] = data["github_url"]
        if "website_url" in data:
            sets["website_url"] = data["website_url"]
        if "tech_tags" in data:
            tags = data["tech_tags"] or []
            if len(tags) > 20:
                raise ValidationException(
                    message="技术标签数量超出上限",
                    error_code=ErrorCode.Validation.VALIDATION_FAILED,
                )
            sets["tech_tags"] = tags

        if sets:
            for key, value in sets.items():
                setattr(user, key, value)
            user.updated_at = now_utc()
            await self.user_repo.update(user)
            await self.db.commit()
            await self.db.refresh(user)
        return user

    async def set_preset_avatar(self, user_id: int, preset_id: int) -> User:
        """设置预设头像（avatar_type=preset）。"""
        if preset_id < 1 or preset_id > _PRESET_COUNT:
            raise ValidationException(
                message="无效的预设头像 ID",
                error_code=ErrorCode.Validation.INVALID_PRESET,
            )
        user = await self.user_service.get_user(user_id)
        user.avatar_url = _PRESET_AVATAR_URL.format(id=preset_id)
        user.avatar_type = "preset"
        user.updated_at = now_utc()
        await self.user_repo.update(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def save_uploaded_avatar(
        self,
        user_id: int,
        content: bytes,
        mime_type: str,
        original_name: str,
        client_meta: Optional[dict] = None,
    ) -> User:
        """保存上传的头像：大小/MIME/扩展名/魔数四重校验，文件名服务端生成。"""
        if len(content) > AVATAR_MAX_SIZE:
            raise ValidationException(
                message=f"文件大小不能超过 {AVATAR_MAX_SIZE // 1024 // 1024}MB",
                error_code=ErrorCode.Validation.FILE_TOO_LARGE,
            )
        if mime_type not in AVATAR_ALLOWED_MIME:
            raise ValidationException(
                message="仅支持 JPEG / PNG / WebP / GIF 格式",
                error_code=ErrorCode.Validation.INVALID_FILE_TYPE,
            )
        ext = Path(original_name).suffix.lower()
        if ext not in AVATAR_ALLOWED_EXT:
            raise ValidationException(
                message="文件扩展名不被允许",
                error_code=ErrorCode.Validation.INVALID_FILE_TYPE,
            )
        if not is_valid_image_mime(content, mime_type):
            raise ValidationException(
                message="文件内容与声明类型不匹配",
                error_code=ErrorCode.Validation.INVALID_FILE_TYPE,
            )

        user = await self.user_service.get_user(user_id)
        _AVATARS_DIR.mkdir(parents=True, exist_ok=True)

        # 文件名服务端生成：user<id>-<timestamp><ext>，不使用原始文件名
        filename = f"user{user_id}-{int(now_utc().timestamp() * 1000)}{ext}"
        try:
            (_AVATARS_DIR / filename).write_bytes(content)
        except OSError as exc:
            raise ValidationException(
                message="头像保存失败",
                error_code=ErrorCode.Validation.FILE_SAVE_FAILED,
            ) from exc

        # 删除旧上传头像（仅 uploaded 类型）
        if user.avatar_type == "uploaded" and user.avatar_url:
            old_name = Path(user.avatar_url).name
            if old_name and old_name != filename:
                try:
                    (_AVATARS_DIR / old_name).unlink(missing_ok=True)
                except OSError:
                    pass  # 旧文件删除失败不阻塞流程

        user.avatar_url = f"/api/avatars/{filename}"
        user.avatar_type = "uploaded"
        user.updated_at = now_utc()
        await self.user_repo.update(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def get_public_profile(self, user_id: int) -> Optional[dict]:
        """用户公开主页（无需登录）：公开资料 + 社区/考试统计。"""
        user = await self.user_repo.get_by_id(user_id)
        if user is None or user.deleted_at is not None or not user.is_active:
            return None

        stats = await self.user_repo.get_public_stats(user_id)

        return {
            "user": {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "bio": user.bio,
                "avatar_url": user.avatar_url,
                "avatar_type": user.avatar_type or "initial",
                "github_url": user.github_url,
                "website_url": user.website_url,
                "tech_tags": user.tech_tags or [],
                "created_at": user.created_at,
            },
            "stats": stats,
        }
