"""数据库配置（ER-55：config.py 拆分子模型，多继承合并保持扁平访问）。"""

import os
from typing import Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        case_sensitive=True,
        extra="ignore",
    )

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

    # 启动时若目标数据库不存在则自动创建（连接到维护库执行 CREATE DATABASE）。
    # 开发便利用 True；生产通常由 DBA/运维预建库，可置 False。
    DB_AUTO_CREATE_DATABASE: bool = True
    DB_MAINTENANCE_DB: str = "postgres"  # 用于建库的维护库名
    # 启动时是否自动执行 alembic upgrade head。
    # 开发/测试建议 True；**生产建议 False**：迁移与发布分离，先跑 job 再起多 worker。
    # True 时多 worker 下仍有 advisory lock 串行化，但更稳妥是独立迁移步骤。
    DB_AUTO_MIGRATE: bool = False

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _strip_database_url(cls, v):
        """仅做轻量清洗：空字符串视作未配置。组装见 _assemble_database_url。"""
        if isinstance(v, str) and not v.strip():
            return None
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

    @property
    def database_url(self) -> str:
        """返回校验后的数据库 URL，并为基础设施层提供非 Optional 类型。"""
        if self.DATABASE_URL is None:
            raise RuntimeError("DATABASE_URL 尚未完成配置校验")
        return self.DATABASE_URL
