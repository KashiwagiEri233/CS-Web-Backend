"""运维配置（ER-55：异常 / 数据保留 / 全文检索 / 可观测性 / 日志）。"""

import os
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpsSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        case_sensitive=True,
        extra="ignore",
    )

    # 异常表默认只保存服务端/业务错误；常规 4xx/422 仅写结构化日志，避免数据库洪泛。
    PERSIST_CLIENT_ERRORS: bool = False
    EXCEPTION_LOG_RETENTION_DAYS: int = Field(30, ge=1)
    EXCEPTION_LOG_CLEANUP_INTERVAL_SECONDS: int = Field(86400, ge=0)

    # 数据保留策略（登录历史 / 审计日志）
    LOGIN_HISTORY_RETENTION_DAYS: int = Field(90, ge=1)
    LOGIN_HISTORY_CLEANUP_INTERVAL_SECONDS: int = Field(86400, ge=0)
    AUDIT_LOG_RETENTION_DAYS: int = Field(365, ge=1)
    AUDIT_LOG_CLEANUP_INTERVAL_SECONDS: int = Field(86400, ge=0)

    # 全文检索配置名：默认 'chinese'（需 zhparser 扩展）；
    # 未装 zhparser 时设为 'simple' 回退（中文无分词，仅整词匹配）。
    FTS_CONFIG: str = "chinese"

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
    # 异步落盘：loguru 默认在调用线程同步写 sink，异步应用里等于事件循环上的阻塞磁盘 IO。
    # None = 用 profile 默认（dev=False 便于调试不丢日志，prod=True 避免阻塞）。
    LOG_ENQUEUE: Optional[bool] = None
