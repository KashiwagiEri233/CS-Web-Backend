"""安全配置（ER-55：JWT / 密钥 / 黑名单 / 分布式撤销状态）。"""

import os
from typing import Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        case_sensitive=True,
        extra="ignore",
    )

    # JWT 配置
    SECRET_KEY: Optional[str] = None  # 强制要求从环境变量设置（见 validate_secret_key）
    # 密钥轮换：逗号分隔的历史 SECRET_KEY 列表；校验时在当前密钥失败后依次尝试。
    # 轮换步骤：1) 把旧 SECRET_KEY 追加到本字段 2) 设置新 SECRET_KEY 3) 等 access 过期后清空本字段。
    JWT_PREVIOUS_SECRET_KEYS: str = ""
    ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "fastapi-witchcat-framework"
    JWT_AUDIENCE: str = "fastapi-witchcat-api"
    # 迁移窗口：允许旧版中完全没有 iss/aud/token_type 的 access token。
    # 默认关闭；仅在从旧系统迁移的短窗口期内显式置 True，迁移结束立即关回。
    JWT_ACCEPT_LEGACY_TOKENS: bool = False
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(15, gt=0)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(7, gt=0)
    # 轮换宽限窗口（秒）：已撤销 refresh token 在窗口内再次被使用视为客户端并发重试
    # （多标签页/网络重试），允许继续轮换而不吊销 family；0 = 关闭宽限，复用即吊销。
    REFRESH_TOKEN_ROTATION_LEEWAY_SECONDS: int = Field(10, ge=0)
    # access token 黑名单（登出/改密后让未过期 token 立即失效）
    #   未配置 Redis 时退回进程内内存黑名单（仅本进程可见，多实例部署会失效）
    #   配置 Redis 后跨实例一致；Redis 不可用时不阻断请求，回退内存
    TOKEN_BLACKLIST_FALLBACK: str = "memory"  # memory / open / closed
    # 高安全生产部署可要求 Redis：True 时
    # 1) 必须配置 REDIS_URL，否则拒绝启动；
    # 2) 启动探测 Redis 失败则拒绝启动（critical）；
    # 3) 强制 TOKEN_BLACKLIST_FALLBACK=closed（Redis 故障时拒绝 access token，禁止静默降级）。
    REQUIRE_REDIS_FOR_SECURITY: bool = False
    # 过期/已撤销 refresh token 清理任务间隔（秒）；0=禁用周期 GC（仅依赖业务撤销）
    REFRESH_TOKEN_GC_INTERVAL_SECONDS: int = Field(3600, ge=0)

    # TOTP 2FA：secret 加密密钥（≥32 字节，必须从环境变量设置，与 SECRET_KEY 同标准）。
    # 迁移兼容：密钥派生算法（HKDF-SHA256 + AES-256-GCM）与前端一致，见 app/core/totp_encryption.py。
    TOTP_ENCRYPTION_KEY: Optional[str] = None
    # 社区浏览去重 IP 哈希密钥（≥16 字节，与 SECRET_KEY 同标准 fail-fast）。
    # 用于匿名化访客 IP 以做浏览去重计数；硬编码常量会令匿名化可逆，故强制从环境读取。
    COMMUNITY_IP_HASH_SECRET: Optional[str] = None

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

    @field_validator("TOTP_ENCRYPTION_KEY", mode="before")
    @classmethod
    def validate_totp_encryption_key(cls, v):
        """TOTP secret 加密密钥：必须 ≥32 UTF-8 字节。

        与 SECRET_KEY 同标准——开发期缺失会导致重启后已加密的 2FA secret 无法
        解密（全部 2FA 失效），必须 fail-fast。
        """
        if v is None or v == "":
            raise ValueError(
                "TOTP_ENCRYPTION_KEY must be set from environment variables"
            )
        if len(v.encode("utf-8")) < 32:
            raise ValueError("TOTP_ENCRYPTION_KEY must contain at least 32 UTF-8 bytes")
        return v

    @field_validator("COMMUNITY_IP_HASH_SECRET", mode="before")
    @classmethod
    def validate_community_ip_hash_secret(cls, v):
        """社区浏览去重 IP 哈希密钥：必须 ≥16 UTF-8 字节。

        与 SECRET_KEY 同标准——缺失会导致 IP 匿名化回退到源码内硬编码常量，
        令匿名化可逆（任何拿到源码的人都能反推访客 IP），必须 fail-fast。
        """
        if v is None or v == "":
            raise ValueError(
                "COMMUNITY_IP_HASH_SECRET must be set from environment variables"
            )
        if len(v.encode("utf-8")) < 16:
            raise ValueError(
                "COMMUNITY_IP_HASH_SECRET must contain at least 16 UTF-8 bytes"
            )
        return v

    @field_validator("TOKEN_BLACKLIST_FALLBACK")
    @classmethod
    def validate_security_fallback(cls, v: str, info) -> str:
        allowed = {"memory", "open"}
        if info.field_name == "TOKEN_BLACKLIST_FALLBACK":
            allowed.add("closed")
        if v not in allowed:
            raise ValueError(f"{info.field_name} must be one of {sorted(allowed)}")
        return v

    @field_validator("ALGORITHM")
    @classmethod
    def validate_algorithm(cls, v: str) -> str:
        # 项目用对称密钥（SECRET_KEY）签发，只允许 HMAC 族；放任意算法字符串
        # （如 RS256）会在签发时直接炸，属不必要的误配置面。
        allowed = {"HS256", "HS384", "HS512"}
        if v not in allowed:
            raise ValueError(f"ALGORITHM 仅支持 {sorted(allowed)}（HMAC 对称签名）")
        return v

    @model_validator(mode="after")
    def _guard_distributed_security_state(self):
        """分布式撤销状态的 fail-closed 配置校验。

        两条检查相互独立，注意顺序：
        1. closed 语义是「Redis 故障时拒绝所有 token」；未配置 REDIS_URL 时客户端
           恒为 None，会永久走 closed 分支 → 全站 401。这条与
           REQUIRE_REDIS_FOR_SECURITY 无关，必须先于下面的提前返回执行。
        2. REQUIRE_REDIS_FOR_SECURITY=True 时还要求配置 REDIS_URL，并强制
           fallback 为 closed（禁止 memory/open 静默降级）；连通性由启动任务
           redis_probe(critical=REQUIRE_REDIS_FOR_SECURITY) 校验。
        """
        if self.TOKEN_BLACKLIST_FALLBACK == "closed" and not self.REDIS_URL:
            raise ValueError(
                "TOKEN_BLACKLIST_FALLBACK=closed 时必须配置 REDIS_URL，"
                "否则黑名单后端恒不可用，所有请求都会被拒绝（401）"
            )

        if not self.REQUIRE_REDIS_FOR_SECURITY:
            return self
        if not self.REDIS_URL:
            raise ValueError(
                "REQUIRE_REDIS_FOR_SECURITY=True 时必须配置 REDIS_URL，"
                "否则多实例 access token 撤销状态无法保持一致"
            )

        # 强制 closed：Redis 故障时拒绝 access token，避免多 worker 静默降级到进程内存
        if self.TOKEN_BLACKLIST_FALLBACK != "closed":
            self.TOKEN_BLACKLIST_FALLBACK = "closed"
        return self
