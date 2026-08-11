"""限流 / Redis / 缓存配置（ER-55）。"""

import os
from typing import Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RateLimitSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        case_sensitive=True,
        extra="ignore",
    )

    # 安全配置（限流）
    RATE_LIMIT_CALLS: int = Field(100, gt=0)
    RATE_LIMIT_PERIOD: int = Field(60, gt=0)
    AUTH_RATE_LIMIT_CALLS: int = Field(5, gt=0)
    AUTH_RATE_LIMIT_PERIOD: int = Field(60, gt=0)
    # 账号级登录防爆破（按用户名计数，弥补仅按 IP 限流挡不住分布式撞库的缺口）。
    # 成功登录也计入预算——真人登录频率远低于该阈值，撞库脚本则会迅速触顶。
    AUTH_ACCOUNT_RATE_LIMIT_CALLS: int = Field(10, gt=0)
    AUTH_ACCOUNT_RATE_LIMIT_PERIOD: int = Field(900, gt=0)
    # 请求体大小上限（字节）。uvicorn 不限制请求体，缺少这道闸门时一个大 JSON
    # 就会被完整读进内存再交给 pydantic。默认 1 MiB，够用于纯 JSON API。
    MAX_REQUEST_BODY_BYTES: int = Field(1024 * 1024, gt=0)

    # Redis 配置（限流/缓存的分布式后端，可选）
    # 留空 = 纯内存模式（单实例，行为同旧版，不引入 Redis 依赖）
    # 配置后 = Redis 跨实例一致限流，且 Redis 不可用时自动降级
    REDIS_URL: Optional[str] = None  # 如 redis://:password@localhost:6379/0
    REDIS_SOCKET_TIMEOUT: float = Field(0.5, gt=0)
    # 连接池上限。redis-py 默认不限（2^31），Redis 侧故障或慢响应时连接会无节制堆积，
    # 直接把 Redis 的 maxclients 打满。按 worker 并发量设置一个明确上限更安全。
    REDIS_MAX_CONNECTIONS: int = Field(50, ge=1)
    # 空闲连接健康检查间隔（秒）：取用前若超过该时长未使用则先 PING，
    # 剔除被防火墙/负载均衡静默掐断的连接。0 = 关闭。
    REDIS_HEALTH_CHECK_INTERVAL: int = Field(30, ge=0)
    # 限流降级策略：Redis 不可用时的兜底行为
    #   memory = 降级到进程内内存限流（默认，仍保护单实例）
    #   open   = 直接放行（牺牲保护换可用性）
    RATE_LIMIT_FALLBACK: str = "memory"
    RATE_LIMIT_REDIS_RETRY_INTERVAL: float = Field(5.0, ge=0)
    # 通用缓存降级策略：Redis 不可用时
    #   memory = 退回进程内缓存（默认）
    #   off    = get 恒未命中、set 静默丢弃（缓存视为可有可无）
    CACHE_FALLBACK: str = "memory"

    @field_validator("RATE_LIMIT_FALLBACK")
    @classmethod
    def validate_rate_limit_fallback(cls, v: str) -> str:
        if v not in {"memory", "open"}:
            raise ValueError("RATE_LIMIT_FALLBACK must be 'memory' or 'open'")
        return v

    @field_validator("CACHE_FALLBACK")
    @classmethod
    def validate_cache_fallback(cls, v: str) -> str:
        if v not in {"memory", "off"}:
            raise ValueError("CACHE_FALLBACK must be 'memory' or 'off'")
        return v

    @model_validator(mode="after")
    def _warn_multi_worker_without_redis(self):
        """多 worker 无 Redis 时发出警告：限流降级到进程内存，实际阈值变为 N×configured。

        不阻止启动（系统仍可运行，只是限流精度下降），但通过 WARNING 让运维感知风险。
        """
        if (
            not self.DEBUG
            and not self.TESTING
            and self.WORKERS > 1
            and not self.REDIS_URL
        ):
            import warnings

            warnings.warn(
                f"生产环境 {self.WORKERS} workers 未配置 REDIS_URL："
                f"限流将降级到进程内存，实际阈值约为 {self.WORKERS}×configured。"
                "建议配置 REDIS_URL 以获得跨 worker 一致的限流。",
                stacklevel=2,
            )
        return self
