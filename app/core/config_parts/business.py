"""业务配置（ER-55：TOTP / 验证码 / 密码 / SMTP / OAuth / LLM）。"""

import os
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BusinessSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        case_sensitive=True,
        extra="ignore",
    )

    # TOTP 2FA 业务参数
    TOTP_ISSUER: str = "FZTBUCS"
    # TOTP 时间步长（秒）与允许的时钟偏移窗口（步）
    TOTP_STEP_SECONDS: int = Field(30, gt=0)
    TOTP_WINDOW_STEPS: int = Field(1, ge=0)
    # 2FA 预认证 token 有效期（分钟）：登录输入密码后、完成 TOTP 前的短期凭证
    TOTP_PRE_AUTH_TTL_MINUTES: int = Field(5, gt=0)

    # 邮箱验证码（注册/找回密码）
    VERIFICATION_CODE_TTL_MINUTES: int = Field(10, gt=0)

    # 密码历史复用检测（N 条；0 = 禁用）
    PASSWORD_HISTORY_LIMIT: int = Field(5, ge=0)
    # 管理员批准重置时使用的默认密码（运行时读取；未配置时审批接口拒绝执行）
    PASSWORD_RESET_DEFAULT: Optional[str] = None

    # SMTP 邮件（SMTP_HOST 为空时回退控制台输出，与前端行为一致）
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = Field(587, gt=0)
    SMTP_SECURE: bool = False  # true = 隐式 TLS（SMTPS），false = STARTTLS
    SMTP_USER: Optional[str] = None
    SMTP_PASS: Optional[str] = None
    SMTP_FROM: str = "no-reply@fztbu.example"
    SMTP_TLS_SKIP_VERIFY: bool = False  # 仅本地开发；生产请配置可信 CA

    # GitHub OAuth（未配置 CLIENT_ID 时 OAuth 登录入口返回未启用）
    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None
    GITHUB_CALLBACK_URL: Optional[str] = (
        None  # 默认 {SITE_URL}/api/auth/oauth/github/callback
    )

    # LLM 学习助手配置（Auxilio Agent）
    # LLM_PROVIDER: openai（OpenAI 兼容协议）/ anthropic / none（禁用，回退规则推荐）
    LLM_PROVIDER: str = "none"
    LLM_API_KEY: Optional[str] = None  # 密钥只存 .env，绝不落库/日志/前端
    LLM_BASE_URL: Optional[str] = (
        None  # OpenAI 兼容自定义网关（Ollama、vLLM 等本地/第三方网关）
    )
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT: float = Field(60, gt=0)
    LLM_MAX_TOKENS: int = Field(1024, gt=0)
    # 单日每用户 LLM 调用预算（0 = 不限制），防成本失控。
    # 单位：千 tokens/日，默认 200 = 20 万 tokens；拦截逻辑在 auxilio_agent.run_chat（llm_usage_logs 按日累加）。
    LLM_DAILY_BUDGET: int = Field(200, ge=0)
    # 学习助手联网搜索工具开关（融合点 4）：false 时 web_search 工具返回未启用提示。
    # 搜索源为 DuckDuckGo 免费 HTML 接口（无需 API key），结果不可信，经 ER-19 包裹注入。
    WEB_SEARCH_ENABLED: bool = True
