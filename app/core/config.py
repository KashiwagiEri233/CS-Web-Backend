import os
from typing import Any, Dict, Optional
from pydantic import validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库配置
    DATABASE_URL: str = "postgresql+asyncpg://postgres:123456@localhost/rqaiqt"
    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str = "rqaiqt"
    DATABASE_USER: str = "postgres"
    DATABASE_PASSWORD: str = "123456"
    
    # JWT 配置
    SECRET_KEY: str = None  # 强制要求从环境变量设置
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # 应用配置
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "FastAPI RBAC Framework"
    
    # CORS配置
    ALLOWED_ORIGINS: list = ["http://localhost:3000", "http://localhost:8080", "http://127.0.0.1:3000", "http://127.0.0.1:8080"]
    ALLOWED_METHODS: list = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    ALLOWED_HEADERS: list = ["*"]
    
    # 安全配置
    RATE_LIMIT_CALLS: int = 100  # 每个时间窗口允许的请求数
    RATE_LIMIT_PERIOD: int = 60  # 时间窗口（秒）
    AUTH_RATE_LIMIT_CALLS: int = 5  # 认证端点每个时间窗口允许的请求数
    AUTH_RATE_LIMIT_PERIOD: int = 60  # 认证端点时间窗口（秒）
    
    @validator("DATABASE_URL", pre=True)
    def assemble_db_connection(cls, v: Optional[str], values: Dict[str, Any]) -> Any:
        if isinstance(v, str):
            return v
        return f"postgresql+asyncpg://{values.get('DATABASE_USER')}:{values.get('DATABASE_PASSWORD')}@{values.get('DATABASE_HOST')}:{values.get('DATABASE_PORT')}/{values.get('DATABASE_NAME')}"
    
    @validator("SECRET_KEY", pre=True)
    def validate_secret_key(cls, v: Optional[str]) -> Any:
        if v is None or v == "":
            raise ValueError("SECRET_KEY must be set from environment variables")
        if v == "your-secret-key-here-change-in-production":
            raise ValueError("Please change the default SECRET_KEY in production environment")
        return v
    
    class Config:
        env_file = os.environ.get("ENV_FILE", ".env")
        case_sensitive = True


# 创建全局配置实例
settings = Settings()