# FastAPI WitchCat Framework

> 女巫猫框架 — 企业级 FastAPI 权限管理脚手架（纯后端）

提供 RBAC 权限控制、JWT 双 Token 认证、结构化异常处理、环境感知日志系统、可降级 Redis 限流/缓存。

## 快速启动

```bash
# 按环境编号启动（通过 --env 指定配置文件）
python run.py --env 1            # 开发环境（.env.development），热重载
python run.py --env 2            # 测试环境（.env.test）
python run.py --prod             # 生产环境（.env）+ 4 workers
python run.py --env 3 --prod     # 等价的显式写法
python run.py --port 9000        # 自定义端口
```

ASGI 部署入口保持为 `app.main:app`；测试或嵌入式使用可调用
`app.main.create_app()` 构造独立的路由/中间件实例。数据库、Redis 和生命周期资源按
“一进程一个应用”模型共享；不要在同一进程并发运行不同配置的应用。

| --env | 配置文件 | 说明 |
|-------|---------|------|
| 1 | `.env.development` | 开发：DEBUG 日志 + 彩色控制台 + Alembic 自动迁移 |
| 2 | `.env.test` | 测试：独立测试数据库 + DEBUG 日志 |
| 3 | `.env` | 生产：INFO 日志 + JSON 序列化 + 文件轮转 + error 日志 |

## 环境配置

本仓库跟踪 `.env.development` / `.env.test` / `.env.example` 作为模板（仅占位凭据）。
**`.env` 不入库**（见 `.gitignore`）；生产密钥请用部署平台 Secret 注入，个人差异放
`.env.local` 或 `.env.*.local`。若历史提交曾含真实密钥，请轮换后清理历史。

1. 使用 **Python 3.13+**（与 `pyproject.toml` / `mypy.ini` / CI 一致），并复制对应环境的模板文件为 `.env`，或直接通过 `--env` 参数指定：
```bash
cp .env.development .env    # 开发（再改成本机密码与 SECRET_KEY）
cp .env.example .env        # 生产模板（务必替换全部 CHANGE_ME）
```

安装依赖（推荐 uv，或 pip + lock）：

```bash
uv sync                     # 或：pip install --require-hashes -r requirements.lock
pip install --require-hashes -r requirements-dev.lock  # 开发/CI/队列（若仍用 pip-tools 锁）
```

修改顶层依赖后，用 Python 3.13 重新生成锁文件（uv 或 pip-tools 均可，输出均为 pip 兼容格式）：

```bash
uv pip compile requirements.txt -o requirements.lock --generate-hashes --python 3.13
uv pip compile requirements-dev.txt -o requirements-dev.lock --generate-hashes --python 3.13
```

应用版本单一事实源：`app/__init__.py` 的 `__version__`（当前与 `pyproject.toml` 对齐为 1.0.0）。

2. 修改配置文件中的 `SECRET_KEY`（至少 32 个 UTF-8 字节）和数据库连接信息（`DATABASE_PASSWORD` 必填，禁止写死默认密码）。多 worker 生产建议 `REQUIRE_REDIS_FOR_SECURITY=True` 并配置可达的 `REDIS_URL`。部署在反向代理后时还要精确配置 `TRUSTED_PROXY_CIDRS`。

## 日志系统

通过 `LOG_PROFILE` 一键切换日志风格，`.env` 中各字段可覆盖 profile 默认值。

| LOG_PROFILE | 级别 | 序列化 | 控制台 | 文件 | Error文件 | 回溯栈 |
|-------------|------|--------|--------|------|-----------|--------|
| `dev` | DEBUG | False(彩色) | True | False | False | True |
| `prod` | INFO | True(JSON) | True | True | True | False |

在 `.env` 中设置：
```bash
LOG_PROFILE=dev   # 开发：DEBUG + 彩色控制台 + 完整回溯栈
LOG_PROFILE=prod  # 生产：INFO + JSON + 文件轮转 + 独立 error 日志
```

可选覆盖字段（取消注释即生效）：
```bash
# LOG_LEVEL=WARNING       # 覆盖级别
# LOG_ENABLE_FILE=True    # 开发环境也开文件日志
# LOG_SERIALIZE=False     # 强制彩色输出
```

## 功能特性

- **RBAC 权限管理**：基于角色的细粒度访问控制，支持权限/角色/用户的完整 CRUD
- **JWT 双 Token 认证**：短期 access token（15分钟）+ 长期 refresh token（7天），支持 token 刷新与黑名单失效
- **Token 黑名单**：登出/改密后让未过期 access token 立即失效（Redis 跨实例 / 内存单实例）
- **结构化异常处理**：统一响应格式、错误码注册表、异常日志持久化到数据库
- **环境感知日志系统**：开发级/线上级独立可配，支持 JSON 序列化与文件轮转
- **可降级限流**：Redis 分布式限流（多实例一致）或内存限流（单实例），Redis 故障自动降级
- **通用缓存**：可降级 Redis/内存缓存后端，支持 TTL 与命名空间
- **性能监控中间件**：请求耗时、QPS、错误率实时统计
- **安全头中间件**：CSP、HSTS、X-Frame-Options 等安全响应头
- **一键鉴权开关**：`AUTH_ENABLED=False` 时全局放行（仅限 DEBUG 模式本地开发）
- **完整的 API 文档**：Swagger / ReDoc 自动生成交互式文档

## 项目结构

```
FastAPI-foundation-framework/
├── app/
│   ├── api/v1/              # 路由层
│   │   ├── auth.py          # 认证（登录/注册/刷新/登出）
│   │   ├── users.py         # 用户管理
│   │   ├── rbac/            # RBAC 权限/角色管理（roles/permissions/assignments/queries）
│   │   ├── exceptions.py    # 异常日志查询
│   │   └── dev_exceptions.py # 异常联调端点（仅 DEBUG 挂载）
│   ├── core/                # 基础设施层
│   │   ├── config.py        # pydantic-settings 配置（.env 映射）
│   │   ├── loguru_logger/   # 环境感知日志封装（adapter/config/context/init）
│   │   ├── security.py      # JWT 签发/校验
│   │   ├── security_blacklist.py  # Token 黑名单（Redis/内存）
│   │   ├── redis_client.py  # Redis 连接（可降级）
│   │   ├── validators.py    # 通用校验器
│   │   ├── cache/           # 通用缓存（Redis/内存后端）
│   │   ├── rate_limit/      # 限流后端（Redis/内存后端）
│   │   └── exceptions/      # 业务异常体系
│   │       ├── base_exceptions.py   # 异常基类
│   │       ├── error_codes.py       # 错误码注册表（命名空间）
│   │       ├── error_builders.py    # 错误响应体构造
│   │       ├── exception_handlers.py  # 全局异常处理器注册
│   │       ├── exception_middleware.py  # 异常处理中间件
│   │       ├── exception_logging.py   # 异常落日志（DB 持久化）
│   │       └── response_models.py     # 统一错误响应体
│   ├── middleware/          # HTTP 中间件
│   │   ├── monitoring.py    # 安全头 + 指标采集 + 请求日志
│   │   ├── rate_limit.py    # 通用限流 + 认证端点限流
│   │   └── rbac.py          # 权限校验依赖（require_permission）
│   ├── models/              # SQLAlchemy 2.0 ORM 模型
│   │   ├── user.py
│   │   ├── role.py
│   │   ├── permission.py
│   │   ├── refresh_token.py
│   │   └── exception_log.py
│   ├── repositories/        # 数据访问层（纯 CRUD）
│   │   ├── user_repo.py
│   │   ├── rbac_repo.py
│   │   ├── refresh_token_repo.py
│   │   └── exception_log_repo.py
│   ├── schemas/             # Pydantic v2 入参/出参
│   │   ├── auth.py
│   │   ├── user.py
│   │   └── rbac.py
│   ├── services/            # 业务逻辑层
│   │   ├── auth_service.py
│   │   ├── rbac_service.py
│   │   ├── rbac_init.py     # 系统初始化（权限/角色/管理员）
│   │   └── exception_service.py
│   ├── utils/               # 跨层纯工具函数
│   │   ├── status.py        # 数据库/应用状态检查
│   │   └── db_initializer.py
│   ├── database.py          # 异步引擎 + get_db / get_session
│   ├── dependencies.py      # 全局依赖
│   └── main.py              # 应用入口（lifespan + 中间件注册）
├── alembic/                 # 数据库迁移（全环境 Schema 唯一来源）
├── tests/                   # 测试代码（目录镜像 app/ 结构）
│   ├── core/                # 核心模块测试
│   ├── integration/         # 集成测试
│   └── middleware/          # 中间件测试
├── docs/                    # 项目文档（按 系统级/业务模块级 分类，见 docs/README.md）
│   ├── README.md            # 文档索引 + 分类约定 + 模板
│   ├── system/              # 系统级（框架/基础设施）
│   └── modules/             # 业务模块级（auth / users / rbac）
├── scripts/                 # 运维脚本
│   └── init_database.py
├── .env.development         # 开发环境模板
├── .env.test                # 测试环境模板
├── .env.example             # 生产环境模板
├── run.py                   # 启动入口（支持 --env 环境切换）
├── requirements.txt         # 运行时顶层依赖
├── requirements.lock        # 运行时传递依赖锁
├── requirements-dev.txt     # 开发/测试/供应链工具顶层依赖
├── requirements-dev.lock    # CI 完整依赖锁（含 hash）
├── pytest.ini               # 测试配置
└── alembic.ini              # 迁移配置
```

## 中间件执行顺序

Starlette 后注册的在更外层，实际执行顺序（外 → 内）：

```
CORS → ExceptionHandler → SecurityHeaders → Logging → Metrics → RateLimit → AuthRateLimit → 路由
```

## 参考文档

| 文档 | 内容 |
|------|------|
| `CLAUDE.md` | 项目定位、技术栈、硬性禁止项、启动速查 |
| `AGENTS.md` | 扩展约定、中心注册点、Alembic 迁移管理、不变量 |
| `ARCHITECTURE.md` | 系统设计与模块关系、分层架构、请求生命周期 |
| `CONVENTIONS.md` | 编码规范、命名、质量红线、安全/错误处理约定 |
| `tests/README.md` | 测试目录组织与运行方式 |
| `docs/README.md` | 模块文档索引、系统级/业务模块级分类约定、文档模板 |
| `docs/system/` | 系统级模块详解（异常体系、可观测性…） |
| `docs/modules/` | 业务模块详解（认证、用户管理、RBAC） |
