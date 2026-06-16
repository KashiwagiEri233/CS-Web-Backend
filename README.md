# FastAPI RBAC Framework

企业级 FastAPI 权限管理脚手架（纯后端），提供 RBAC 权限控制、JWT 认证、结构化异常处理、环境感知日志系统。

## 快速启动

```bash
# 按环境编号启动（通过 --env 指定配置文件）
python run.py --env 1            # 开发环境（.env.development），热重载
python run.py --env 2            # 测试环境（.env.test）
python run.py --env 3            # 生产环境（.env）
python run.py --env 3 --prod     # 生产环境 + 多 worker（4 workers）
python run.py --port 9000        # 自定义端口
```

| --env | 配置文件 | 说明 |
|-------|---------|------|
| 1 | `.env.development` | 开发：DEBUG 日志 + 彩色控制台 |
| 2 | `.env.test` | 测试：独立测试数据库 + DEBUG 日志 |
| 3 | `.env` | 生产：INFO 日志 + JSON 序列化 + 文件轮转 + error 日志 |

## 环境配置

1. 复制对应环境的模板文件为 `.env`，或直接通过 `--env` 参数指定：
```bash
cp .env.development .env    # 开发
cp .env.example .env        # 生产
```

2. 修改配置文件中的 `SECRET_KEY` 和数据库连接信息。

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

- 基于角色的访问控制 (RBAC)
- JWT 认证与授权
- 环境感知日志系统（开发级/线上级独立可配）
- 统一异常处理体系
- 速率限制中间件
- 性能监控中间件
- 安全头中间件
- 完整的 API 文档 (Swagger / ReDoc)

## 项目结构

```
FastAPI-foundation-framework/
├── app/
│   ├── api/v1/          # 路由层（auth/users/rbac/exceptions）
│   ├── core/            # config / loguru_logger / security / exceptions
│   ├── middleware/      # monitoring / rate_limit / rbac
│   ├── models/          # ORM 模型
│   ├── repositories/    # 数据访问层
│   ├── schemas/         # Pydantic 入参/出参
│   ├── services/        # 业务逻辑层
│   └── main.py          # 应用入口
├── alembic/             # 数据库迁移
├── tests/               # 测试代码
├── .env.development     # 开发环境模板
├── .env.test            # 测试环境模板
├── .env.example         # 生产环境模板
├── run.py               # 启动入口（支持 --env 环境切换）
└── requirements.txt     # 依赖列表
```
