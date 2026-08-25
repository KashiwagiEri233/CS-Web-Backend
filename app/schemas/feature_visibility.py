"""功能模块可见性 — Schema。

复用 settings 表存储（module="feature_visibility"），无需新表迁移。
JSON 传输统一 camelCase（alias_generator=to_camel），Python 属性 snake_case。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.schemas.base import TZModel


def _camel(*, from_attributes: bool = False) -> ConfigDict:
    config: ConfigDict = {"alias_generator": to_camel, "populate_by_name": True}
    if from_attributes:
        config["from_attributes"] = True
    return config


class VisibilityRule(BaseModel):
    """三类用户的可见性开关。"""

    model_config = _camel()

    guest: bool = Field(..., description="未登录是否可见")
    member: bool = Field(..., description="已登录普通用户是否可见")
    admin: bool = Field(..., description="管理员（admin/root）是否可见")


class ModuleVisibility(TZModel):
    """单个模块的可见性配置（列表项 / 更新返回）。"""

    model_config = _camel(from_attributes=True)

    module_key: str = Field(..., min_length=1, max_length=50, description="模块标识")
    guest: bool
    member: bool
    admin: bool


class FeatureVisibilityConfig(BaseModel):
    """全部受管模块的可见性配置聚合。"""

    model_config = _camel()

    modules: list[ModuleVisibility]


class UpdateVisibilityRequest(BaseModel):
    """更新单模块可见性请求体（module_key 在 URL 路径中）。

    强制 2FA（决策 B）：root 必须已启用 2FA 且携带有效 TOTP 码。
    """

    model_config = _camel()

    guest: bool
    member: bool
    admin: bool
    totp_code: str = Field(..., min_length=6, max_length=6, description="两步验证码")
