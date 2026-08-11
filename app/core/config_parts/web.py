"""应用 / 站点 / 网络配置（ER-55：DEBUG、CORS、可信代理、时区、管理员）。"""

import os
from datetime import timezone, tzinfo
from ipaddress import ip_network
from typing import Optional

from pydantic import Field, PrivateAttr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class WebSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        case_sensitive=True,
        extra="ignore",
    )

    _tzinfo: tzinfo = PrivateAttr(default=timezone.utc)
    _trusted_proxy_networks: tuple = PrivateAttr(default=())

    # ---- 应用配置 ----
    DEBUG: bool = False
    # 测试进程使用 NullPool，避免 pytest 每测试事件循环与 asyncpg 池连接交叉复用。
    TESTING: bool = False
    # uvicorn worker 数量（run.py 写入环境变量）。用于启动时校验多 worker + 无 Redis 的限流降级风险。
    WORKERS: int = Field(1, ge=1)
    API_V1_STR: str = "/api/v1"
    # 是否暴露 /docs、/redoc、/openapi.json。
    # None（默认）= 跟随 DEBUG：生产（DEBUG=False）自动关闭，避免未认证用户
    # 拿到完整 API 结构与全部 schema。需要在生产开放时显式置 True。
    ENABLE_API_DOCS: Optional[bool] = None
    PROJECT_NAME: str = "FastAPI RBAC Framework"
    # 应用统一时区（IANA 名称，如 Asia/Shanghai、UTC、America/New_York）。
    # 影响：展示层（日志、错误响应 timestamp、ErrorResponse.timestamp）按此时区呈现。
    # 存储层（数据库、JWT exp）一律 UTC，保证跨时区一致性。
    # 留空 / "UTC" = UTC（行为与改造前完全一致，向后兼容）。
    TIMEZONE: str = "UTC"
    # 一键开关鉴权：False 时所有接口视为超级用户放行（跳过 token 校验与权限检查）。
    # 仅限本地开发！只允许在 DEBUG=True 下关闭，生产（DEBUG=False）若置 False 会拒绝启动。
    AUTH_ENABLED: bool = True

    # ---- 站点 / 业务配置（前后端分离迁移 Phase 1） ----
    # 站点公网地址（BFF 域名），用于构造 OAuth 回调等默认 URL
    SITE_URL: str = "http://localhost:2333"

    # 默认管理员（仅在数据库首次初始化、且该用户不存在时创建）
    ADMIN_USERNAME: str = "admin"
    ADMIN_EMAIL: str = "admin@example.com"
    # 已有管理员时可留空；首次创建时必须配置。密码永不写入日志。
    ADMIN_PASSWORD: Optional[str] = None

    # ---- CORS配置（.env 文件里写逗号分隔字符串，如 ALLOWED_ORIGINS=http://a,http://b）----
    # 用 str 类型 + validator 转 list，避免 pydantic-settings v2 对 list 字段强制 JSON 解析
    ALLOWED_ORIGINS: str = (
        "http://localhost:3000,http://localhost:8080,"
        "http://127.0.0.1:3000,http://127.0.0.1:8080"
    )
    ALLOWED_METHODS: str = "GET,POST,PUT,DELETE,OPTIONS"
    ALLOWED_HEADERS: str = "*"
    # 只有来自这些可信反向代理网段的 X-Forwarded-For / X-Real-IP 才会被采用。
    # 留空表示完全忽略转发头，直接使用 TCP 对端地址。
    TRUSTED_PROXY_CIDRS: str = ""

    @field_validator(
        "ALLOWED_ORIGINS", "ALLOWED_METHODS", "ALLOWED_HEADERS", mode="before"
    )
    @classmethod
    def parse_comma_separated_list(cls, v):
        """统一接受 str（逗号分隔）或 list 输入，存储为逗号分隔 str。

        main.py 通过 allowed_origins_list / allowed_methods_list / allowed_headers_list
        获取 list 形式（见下方 model_validator）。
        """
        if isinstance(v, list):
            return ",".join(str(item) for item in v)
        return v

    @property
    def allowed_origins_list(self) -> list[str]:
        return [s.strip() for s in self.ALLOWED_ORIGINS.split(",") if s.strip()]

    @property
    def allowed_methods_list(self) -> list[str]:
        return [s.strip() for s in self.ALLOWED_METHODS.split(",") if s.strip()]

    @property
    def allowed_headers_list(self) -> list[str]:
        return [s.strip() for s in self.ALLOWED_HEADERS.split(",") if s.strip()]

    @property
    def trusted_proxy_networks(self) -> tuple:
        """返回已校验的可信代理 IP 网段（model_validator 解析一次后缓存）。"""
        return self._trusted_proxy_networks

    @field_validator("TRUSTED_PROXY_CIDRS")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, v: str) -> str:
        for item in v.split(","):
            if item.strip():
                ip_network(item.strip(), strict=False)
        return v

    @model_validator(mode="after")
    def _parse_trusted_proxy_networks(self):
        """把 TRUSTED_PROXY_CIDRS 解析结果缓存到 _trusted_proxy_networks。

        get_client_ip 是每请求路径，XFF 链检查会遍历网段；避免每请求重复
        split + ip_network 重建（与 _validate_timezone 缓存 _tzinfo 同模式）。
        """
        self._trusted_proxy_networks = tuple(
            ip_network(item.strip(), strict=False)
            for item in self.TRUSTED_PROXY_CIDRS.split(",")
            if item.strip()
        )
        return self

    @model_validator(mode="after")
    def _guard_auth_disabled(self):
        # 生产安全锁：禁止在非 DEBUG 环境关闭鉴权
        if not self.AUTH_ENABLED and not self.DEBUG:
            raise ValueError(
                "AUTH_ENABLED=False 仅允许在 DEBUG=True 下使用；生产环境禁止关闭鉴权"
            )
        return self

    @model_validator(mode="after")
    def _validate_timezone(self):
        """校验 TIMEZONE 是合法 IANA 时区名，并把解析结果缓存到 _tzinfo。

        非法名直接拒绝启动（快速失败优于静默回退到错误时区）。
        """
        tz_name = (self.TIMEZONE or "UTC").strip() or "UTC"
        # UTC 直接回退 timezone.utc，避免 Windows 缺少 tzdata 时 ZoneInfo 报错
        if tz_name.upper() == "UTC":
            self._tzinfo = timezone.utc
            self.TIMEZONE = "UTC"
            return self
        try:
            # ZoneInfo 缓存命中时不触发磁盘 IO，因此每次校验成本极低
            self._tzinfo = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"TIMEZONE 配置非法：{tz_name!r} 不是有效的 IANA 时区名"
                "（示例：Asia/Shanghai / UTC / America/New_York）"
            ) from exc
        self.TIMEZONE = tz_name  # 规范化（去空白）
        return self

    @property
    def tzinfo(self):
        """已校验的 ZoneInfo 实例，供展示层转换使用。"""
        return self._tzinfo

    @property
    def api_docs_enabled(self) -> bool:
        """交互式文档是否开放。未显式配置时跟随 DEBUG。"""
        if self.ENABLE_API_DOCS is None:
            return self.DEBUG
        return self.ENABLE_API_DOCS
