# FastAPI RBAC Framework

企业级FastAPI权限管理框架，提供优雅的启动体验和完善的RBAC权限控制系统。

## 快速启动

```bash
python run.py              # 开发模式（热重载）
python run.py --prod       # 生产模式（多 worker）
python run.py --port 9000  # 自定义端口
```

## 环境配置

1. 复制环境变量配置文件：
```bash
cp .env.example .env
```

2. 根据需要修改 `.env` 文件中的配置

## 功能特性

- 🔐 基于角色的访问控制(RBAC)
- 📊 结构化日志记录
- 🛡️ 安全中间件
- 📈 性能监控
- 🚀 优雅的启动流程
- 📝 完整的API文档

## 项目结构

```
FastAPI-foundation-framework/
├── app/                 # 应用核心代码
│   ├── api/            # API路由
│   ├── core/           # 核心配置
│   ├── models/         # 数据模型
│   └── middleware/     # 中间件
├── logs/               # 日志文件目录
├── tests/              # 测试代码
├── run.py              # 统一启动入口
└── requirements.txt    # 依赖包列表
```