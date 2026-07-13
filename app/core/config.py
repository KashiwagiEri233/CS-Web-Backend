import os
from datetime import timezone, tzinfo
from typing import Optional
from ipaddress import ip_network

from pydantic import Field, PrivateAttr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class Settings(BaseSettings):
    _tzinfo: tzinfo = PrivateAttr(default=timezone.utc)

    # 数据库配置
    # DATABASE_URL 与 DATABASE_PASSWORD 均不提供默认值，强制从环境变量设置（与 SECRET_KEY 同标准）。
    # 单独的 host/port/name/user 保留本地默认值（不含密码）。
    # 组装逻辑见 _assemble_database_url (model_validator mode=after)，
    # 此时所有字段均已处理，可安全引用。
    DATABASE_URL: Optional[str] = None
    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str = "domefff"
    DATABASE_USER: str = "postgres"
    DATABASE_PASSWORD: Optional[str] = None

    # 连接池（生产参数）。异步引擎默认 AsyncAdaptedQueuePool。
    DB_POOL_SIZE: int = Field(10, ge=1)  # 常驻连接数
    DB_MAX_OVERFLOW: int = Field(20, ge=0)  # 峰值可额外创建的连接数
    DB_POOL_TIMEOUT: int = Field(30, gt=0)  # 池满时等待可用连接的超时（秒）
    DB_POOL_RECYCLE: int = Field(
        1800, ge=0
    )  # 连接最大存活（秒），主动回收，避免被 PG/中间件掐断的陈旧连接
    DB_POOL_PRE_PING: bool = True  # 取连接前先 ping，自动剔除失效连接（生产强烈建议开）

    # JWT 配置
    SECRET_KEY: Optional[str] = None  # 强制要求从环境变量设置（见 validate_secret_key）
    # 密钥轮换：逗号分隔的历史 SECRET_KEY 列表；校验时在当前密钥失败后依次尝试。
    # 轮换步骤：1) 把旧 SECRET_KEY 追加到本字段 2) 设置新 SECRET_KEY 3) 等 access 过期后清空本字段。
    JWT_PREVIOUS_SECRET_KEYS: str = ""
    ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "fastapi-witchcat-framework"
    JWT_AUDIENCE: str = "fastapi-witchcat-api"
    # 迁移窗口：允许旧版中完全没有 iss/aud/token_type 的 access token。
    # 新项目/迁移窗口结束后应置 False。
    JWT_ACCEPT_LEGACY_TOKENS: bool = True
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(15, gt=0)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(7, gt=0)
    # access token 黑名单（登出/改密后让未过期 token 立即失效）
    #   未配置 Redis 时退回进程内内存黑名单（仅本进程可见，多实例部署会失效）
    #   配置 Redis 后跨实例一致；Redis 不可用时不阻断请求，回退内存
    TOKEN_BLACKLIST_FALLBACK: str = "memory"  # memory / open / closed
    # 高安全生产部署可要求 Redis；用于保证多 worker 的登出/封禁状态一致。
    REQUIRE_REDIS_FOR_SECURITY: bool = False
    # 过期/已撤销 refresh token 清理任务间隔（秒）；0=禁用周期 GC（仅依赖业务撤销）
    REFRESH_TOKEN_GC_INTERVAL_SECONDS: int = Field(3600, ge=0)

    # 异常表默认只保存服务端/业务错误；常规 4xx/422 仅写结构化日志，避免数据库洪泛。
    PERSIST_CLIENT_ERRORS: bool = False
    EXCEPTION_LOG_RETENTION_DAYS: int = Field(30, ge=1)
    EXCEPTION_LOG_CLEANUP_INTERVAL_SECONDS: int = Field(86400, ge=0)

    # 默认管理员（仅在数据库首次初始化、且该用户不存在时创建）
    ADMIN_USERNAME: str = "admin"
    ADMIN_EMAIL: str = "admin@example.com"
    # 已有管理员时可留空；首次创建时必须配置。密码永不写入日志。
    ADMIN_PASSWORD: Optional[str] = None

    # 应用配置
    DEBUG: bool = False
    # 测试进程使用 NullPool，避免 pytest 每测试事件循环与 asyncpg 池连接交叉复用。
    TESTING: bool = False
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "FastAPI RBAC Framework"
    # 应用统一时区（IANA 名称，如 Asia/Shanghai、UTC、America/New_York）。
    # 影响：展示层（日志、错误响应 timestamp、ErrorResponse.timestamp）按此时区呈现。
    # 存储层（数据库、JWT exp）一律 UTC，保证跨时区一致性。
    # 留空 / "UTC" = UTC（行为与改造前完全一致，向后兼容）。
    TIMEZONE: str = "UTC"
    # 一键开关鉴权：False 时所有接口视为超级用户放行（跳过 token 校验与权限检查）。
    # 仅限本地开发！只允许在 DEBUG=True 下关闭，生产（DEBUG=False）若置 False 会拒绝启动。
    AUTH_ENABLED: bool = True
    # 【已废弃】历史开关：曾用 Base.metadata.create_all 自动建表。
    # 现已全面改为 Alembic 管理 schema；启动路径**忽略**此字段（即使 True 也不 create_all）。
    # 保留仅为兼容旧 .env，请从配置中删除，勿再开启。
    DB_AUTO_CREATE: bool = False
    # 启动时若目标数据库不存在则自动创建（连接到维护库执行 CREATE DATABASE）。
    # 开发便利用 True；生产通常由 DBA/运维预建库，可置 False。
    DB_AUTO_CREATE_DATABASE: bool = True
    DB_MAINTENANCE_DB: str = "postgres"  # 用于建库的维护库名
    # 启动时是否自动执行 alembic upgrade head。
    # 开发/测试建议 True；**生产建议 False**：迁移与发布分离，先跑 job 再起多 worker。
    # True 时多 worker 下仍有 advisory lock 串行化，但更稳妥是独立迁移步骤。
    DB_AUTO_MIGRATE: bool = False

    # CORS配置（.env 文件里写逗号分隔字符串，如 ALLOWED_ORIGINS=http://a,http://b）
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

    # 安全配置
    RATE_LIMIT_CALLS: int = Field(100, gt=0)
    RATE_LIMIT_PERIOD: int = Field(60, gt=0)
    AUTH_RATE_LIMIT_CALLS: int = Field(5, gt=0)
    AUTH_RATE_LIMIT_PERIOD: int = Field(60, gt=0)

    # Redis 配置（限流/缓存的分布式后端，可选）
    # 留空 = 纯内存模式（单实例，行为同旧版，不引入 Redis 依赖）
    # 配置后 = Redis 跨实例一致限流，且 Redis 不可用时自动降级
    REDIS_URL: Optional[str] = None  # 如 redis://:password@localhost:6379/0
    REDIS_SOCKET_TIMEOUT: float = Field(0.5, gt=0)
    # 限流降级策略：Redis 不可用时的兜底行为
    #   memory = 降级到进程内内存限流（默认，仍保护单实例）
    #   open   = 直接放行（牺牲保护换可用性）
    RATE_LIMIT_FALLBACK: str = "memory"
    RATE_LIMIT_REDIS_RETRY_INTERVAL: float = Field(5.0, ge=0)
    # 通用缓存降级策略：Redis 不可用时
    #   memory = 退回进程内缓存（默认）
    #   off    = get 恒未命中、set 静默丢弃（缓存视为可有可无）
    CACHE_FALLBACK: str = "memory"

    # 可观测性（OpenTelemetry，可选，默认关闭）
    # 与 Redis 同理当作增强项：OTEL_ENABLED=False 时完全 no-op，不引入任何运行时开销；
    # 启用但未配 endpoint 时降级为控制台导出（仅适合本地调试），绝不阻断启动。
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "fastapi-rbac-framework"
    # OTLP collector 端点（如 http://localhost:4317）。留空 + 启用 = 降级控制台导出。
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = None
    OTEL_EXPORTER_OTLP_PROTOCOL: str = "grpc"  # grpc 或 http/protobuf
    OTEL_TRACES_SAMPLER_RATIO: float = Field(1.0, ge=0.0, le=1.0)
    OTEL_CONSOLE_EXPORT: bool = False  # 强制控制台导出（本地调试用，优先于 OTLP）

    # 日志配置
    # LOG_PROFILE 是一键开关：dev=开发级（彩色控制台+DEBUG），prod=生产级（JSON+文件轮转+ERROR日志）
    # 选定 profile 后，下方字段留 None=用 profile 默认；赋值则覆盖
    LOG_PROFILE: str = "dev"  # dev 或 prod
    LOG_LEVEL: str = ""  # 留空=按 profile 默认
    LOG_DIR: str = "logs"
    LOG_ROTATION: str = "10 MB"
    LOG_RETENTION: str = "30 days"
    # 以下字段 None=用 profile 默认值，取消注释赋值则覆盖
    LOG_SERIALIZE: Optional[bool] = None
    LOG_BACKTRACE: Optional[bool] = None
    LOG_ENABLE_CONSOLE: Optional[bool] = None
    LOG_ENABLE_FILE: Optional[bool] = None
    LOG_ENABLE_ERROR_FILE: Optional[bool] = None

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _strip_database_url(cls, v):
        """仅做轻量清洗：空字符串视作未配置。组装见 _assemble_database_url。"""
        if isinstance(v, str) and not v.strip():
            return None
        return v

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
        """返回已校验的可信代理 IP 网段。"""
        return tuple(
            ip_network(item.strip(), strict=False)
            for item in self.TRUSTED_PROXY_CIDRS.split(",")
            if item.strip()
        )

    @field_validator("SECRET_KEY", mode="before")
    @classmethod
    def validate_secret_key(cls, v):
        if v is None or v == "":
            raise ValueError("SECRET_KEY must be set from environment variables")
        if v == "your-secret-key-here-change-in-production":
            raise ValueError(
                "Please change the default SECRET_KEY in production environment"
            )
        if len(v.encode("utf-8")) < 32:
            raise ValueError("SECRET_KEY must contain at least 32 UTF-8 bytes")
        return v

    @field_validator("TRUSTED_PROXY_CIDRS")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, v: str) -> str:
        for item in v.split(","):
            if item.strip():
                ip_network(item.strip(), strict=False)
        return v

    @field_validator("TOKEN_BLACKLIST_FALLBACK", "RATE_LIMIT_FALLBACK")
    @classmethod
    def validate_security_fallback(cls, v: str, info) -> str:
        allowed = {"memory", "open"}
        if info.field_name == "TOKEN_BLACKLIST_FALLBACK":
            allowed.add("closed")
        if v not in allowed:
            raise ValueError(f"{info.field_name} must be one of {sorted(allowed)}")
        return v

    @field_validator("CACHE_FALLBACK")
    @classmethod
    def validate_cache_fallback(cls, v: str) -> str:
        if v not in {"memory", "off"}:
            raise ValueError("CACHE_FALLBACK must be 'memory' or 'off'")
        return v

    @model_validator(mode="after")
    def _assemble_database_url(self):
        """组装数据库连接 URL 并校验凭据。

        优先使用显式配置的 DATABASE_URL；否则由 host/port/name/user/password 组装。
        DATABASE_PASSWORD 与 DATABASE_URL 均无默认值（与 SECRET_KEY 同标准），
        两者同时缺失时直接拒绝启动，避免无意中用无密码连接跑起来。
        """
        if self.DATABASE_URL:
            return self

        if not self.DATABASE_PASSWORD:
            raise ValueError(
                "DATABASE_URL 或 DATABASE_PASSWORD 必须从环境变量设置；"
                "不允许使用无密码或写死密码的默认连接"
            )

        from sqlalchemy.engine import URL

        self.DATABASE_URL = URL.create(
            drivername="postgresql+asyncpg",
            username=self.DATABASE_USER,
            password=self.DATABASE_PASSWORD,
            host=self.DATABASE_HOST,
            port=self.DATABASE_PORT,
            database=self.DATABASE_NAME,
        ).render_as_string(hide_password=False)
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
    def _guard_distributed_security_state(self):
        if self.REQUIRE_REDIS_FOR_SECURITY and not self.REDIS_URL:
            raise ValueError(
                "REQUIRE_REDIS_FOR_SECURITY=True 时必须配置 REDIS_URL，"
                "否则多实例 access token 撤销状态无法保持一致"
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
    def database_url(self) -> str:
        """返回校验后的数据库 URL，并为基础设施层提供非 Optional 类型。"""
        if self.DATABASE_URL is None:
            raise RuntimeError("DATABASE_URL 尚未完成配置校验")
        return self.DATABASE_URL

    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        case_sensitive=True,
        extra="ignore",
    )


# 创建全局配置实例
settings = Settings()
