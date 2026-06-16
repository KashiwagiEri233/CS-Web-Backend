import os
from typing import Optional
from pydantic import field_validator, ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 数据库配置
    DATABASE_URL: str = "postgresql+asyncpg://postgres:123456@localhost/rqaiqt"
    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str = "rqaiqt"
    DATABASE_USER: str = "postgres"
    DATABASE_PASSWORD: str = "123456"
    
    # JWT 配置
    SECRET_KEY: Optional[str] = None  # 强制要求从环境变量设置（见 validate_secret_key）
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

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
    # 启动时是否用 Base.metadata.create_all 自动建表。
    # 开发环境置 True 方便起步；生产环境应置 False，改用 `alembic upgrade head` 管理 schema，
    # 避免 create_all 与迁移双轨并存导致的不一致。
    DB_AUTO_CREATE: bool = True
    # 启动时若目标数据库不存在则自动创建（连接到维护库执行 CREATE DATABASE）。
    # 开发便利用 True；生产通常由 DBA/运维预建库，可置 False。
    DB_AUTO_CREATE_DATABASE: bool = True
    DB_MAINTENANCE_DB: str = "postgres"  # 用于建库的维护库名
    
    # CORS配置
    ALLOWED_ORIGINS: list = ["http://localhost:3000", "http://localhost:8080", "http://127.0.0.1:3000", "http://127.0.0.1:8080"]
    ALLOWED_METHODS: list = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    ALLOWED_HEADERS: list = ["*"]
    
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
    def assemble_db_connection(cls, v, info: ValidationInfo):
        if isinstance(v, str):
            return v
        d = info.data
        return (
            f"postgresql+asyncpg://{d.get('DATABASE_USER')}:{d.get('DATABASE_PASSWORD')}"
            f"@{d.get('DATABASE_HOST')}:{d.get('DATABASE_PORT')}/{d.get('DATABASE_NAME')}"
        )

    @field_validator("SECRET_KEY", mode="before")
    @classmethod
    def validate_secret_key(cls, v):
        if v is None or v == "":
            raise ValueError("SECRET_KEY must be set from environment variables")
        if v == "your-secret-key-here-change-in-production":
            raise ValueError("Please change the default SECRET_KEY in production environment")
        return v

    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        case_sensitive=True,
        extra="ignore",
    )


# 创建全局配置实例
settings = Settings()