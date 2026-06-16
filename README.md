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

每个日志参数独立可配，开发环境也能按需开启文件/JSON/error 日志。

| 配置项 | 开发推荐 | 生产推荐 | 说明 |
|--------|---------|---------|------|
| LOG_LEVEL | DEBUG | INFO | 日志级别 |
| LOG_SERIALIZE | False | True | JSON 序列化（线上采集用） |
| LOG_ENABLE_CONSOLE | True | True | 控制台输出 |
| LOG_ENABLE_FILE | False | True | 全级别文件日志 |
| LOG_ENABLE_ERROR_FILE | False | True | 独立 ERROR 日志文件 |
| LOG_BACKTRACE | True | False | 完整回溯栈 |
| LOG_ROTATION | 10 MB | 10 MB | 文件轮转大小 |
| LOG_RETENTION | 30 days | 30 days | 保留时间 |

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
