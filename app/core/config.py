"""全局配置聚合（ER-55：按域拆分 config_parts 子模块，多继承合并保持扁平访问）。

拆分前本文件为 518 行单类。现按域拆为 app/core/config_parts/ 下的子模型：
  - database.py   DatabaseSettings   数据库 URL / 连接池 / 建库迁移
  - security.py   SecuritySettings   JWT / 密钥 / 黑名单 / 分布式撤销状态
  - web.py        WebSettings        应用开关 / 站点 / CORS / 可信代理 / 时区 / 管理员
  - rate_limit.py RateLimitSettings  限流 / Redis / 缓存降级
  - ops.py        OpsSettings        异常 / 数据保留 / FTS / OTEL / 日志
  - business.py   BusinessSettings   TOTP / 验证码 / 密码 / SMTP / OAuth / LLM

聚合类多继承合并字段，`settings.X` 扁平访问与拆分前完全一致；校验器/属性随
字段归属子模块，跨域 model_validator 引用兄弟类字段在最终实例上均可见。
"""

import os

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config_parts.business import BusinessSettings
from app.core.config_parts.database import DatabaseSettings
from app.core.config_parts.ops import OpsSettings
from app.core.config_parts.rate_limit import RateLimitSettings
from app.core.config_parts.security import SecuritySettings
from app.core.config_parts.web import WebSettings


class Settings(
    DatabaseSettings,
    SecuritySettings,
    WebSettings,
    RateLimitSettings,
    OpsSettings,
    BusinessSettings,
):
    """聚合配置：全部配置字段扁平可见（settings.X），与拆分前行为一致。"""

    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        case_sensitive=True,
        extra="ignore",
    )


# 创建全局配置实例
settings = Settings()
