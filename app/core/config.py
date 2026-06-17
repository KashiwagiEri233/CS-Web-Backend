import os
from typing import Optional
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
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
    
    # JWT 配置
    SECRET_KEY: Optional[str] = None  # 强制要求从环境变量设置（见 validate_secret_key）
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15  # 短期 access token（分钟），配合 refresh token 使用
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7  # 长期 refresh token（天）
    # access token 黑名单（登出/改密后让未过期 token 立即失效）
    #   未配置 Redis 时退回进程内内存黑名单（仅本进程可见，多实例部署会失效）
    #   配置 Redis 后跨实例一致；Redis 不可用时不阻断请求，回退内存
    TOKEN_BLACKLIST_FALLBACK: str = "memory"  # memory=降级内存 / open=故障时放行（不推荐）

    # 默认管理员（仅在数据库首次初始化、且该用户不存在时创建）
    ADMIN_USERNAME: str = "admin"
    ADMIN_EMAIL: str = "admin@example.com"
    # 留空 = 首启随机生成强密码并在日志中提示一次（请立即登录修改）；
    # 设置了值 = 用该密码且绝不写入日志。
    ADMIN_PASSWORD: Optional[str] = None
    
    # 应用配置
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "FastAPI RBAC Framework"
    # 一键开关鉴权：False 时所有接口视为超级用户放行（跳过 token 校验与权限检查）。
    # 仅限本地开发！只允许在 DEBUG=True 下关闭，生产（DEBUG=False）若置 False 会拒绝启动。
    AUTH_ENABLED: bool = True
    # 启动时是否用 Base.metadata.create_all 自动建表。
    # 开发环境置 True 方便起步；生产环境应置 False，改用 `alembic upgrade head` 管理 schema，
    # 避免 create_all 与迁移双轨并存导致的不一致。
    DB_AUTO_CREATE: bool = True
    # 启动时若目标数据库不存在则自动创建（连接到维护库执行 CREATE DATABASE）。
    # 开发便利用 True；生产通常由 DBA/运维预建库，可置 False。
    DB_AUTO_CREATE_DATABASE: bool = True
    DB_MAINTENANCE_DB: str = "postgres"  # 用于建库的维护库名
    
    # CORS配置（.env 文件里写逗号分隔字符串，如 ALLOWED_ORIGINS=http://a,http://b）
    # 用 str 类型 + validator 转 list，避免 pydantic-settings v2 对 list 字段强制 JSON 解析
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:8080,http://127.0.0.1:3000,http://127.0.0.1:8080"
    ALLOWED_METHODS: str = "GET,POST,PUT,DELETE,OPTIONS"
    ALLOWED_HEADERS: str = "*"
    
    # 安全配置
    RATE_LIMIT_CALLS: int = 100  # 每个时间窗口允许的请求数
    RATE_LIMIT_PERIOD: int = 60  # 时间窗口（秒）
    AUTH_RATE_LIMIT_CALLS: int = 5  # 认证端点每个时间窗口允许的请求数
    AUTH_RATE_LIMIT_PERIOD: int = 60  # 认证端点时间窗口（秒）

    # Redis 配置（限流/缓存的分布式后端，可选）
    # 留空 = 纯内存模式（单实例，行为同旧版，不引入 Redis 依赖）
    # 配置后 = Redis 跨实例一致限流，且 Redis 不可用时自动降级
    REDIS_URL: Optional[str] = None  # 如 redis://:password@localhost:6379/0
    REDIS_SOCKET_TIMEOUT: float = 0.5  # 连接/读写超时（秒），设小以便 Redis 故障时快速降级
    # 限流降级策略：Redis 不可用时的兜底行为
    #   memory = 降级到进程内内存限流（默认，仍保护单实例）
    #   open   = 直接放行（牺牲保护换可用性）
    RATE_LIMIT_FALLBACK: str = "memory"
    RATE_LIMIT_REDIS_RETRY_INTERVAL: float = 5.0  # 降级后多少秒尝试半开重连 Redis
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
    OTEL_TRACES_SAMPLER_RATIO: float = 1.0  # 采样率 0.0~1.0；生产高流量可调小
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

    @field_validator("ALLOWED_ORIGINS", "ALLOWED_METHODS", "ALLOWED_HEADERS", mode="before")
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

    @field_validator("SECRET_KEY", mode="before")
    @classmethod
    def validate_secret_key(cls, v):
        if v is None or v == "":
            raise ValueError("SECRET_KEY must be set from environment variables")
        if v == "your-secret-key-here-change-in-production":
            raise ValueError("Please change the default SECRET_KEY in production environment")
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

        self.DATABASE_URL = (
            f"postgresql+asyncpg://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
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

    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        case_sensitive=True,
        extra="ignore",
    )


# 创建全局配置实例
settings = Settings()