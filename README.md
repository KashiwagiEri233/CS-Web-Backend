# FastAPI RBAC Framework

企业级FastAPI权限管理框架，提供优雅的启动体验和完善的RBAC权限控制系统。

## 快速启动

### 使用优雅启动脚本（推荐）

```bash
python startup.py
```

这将提供更简洁的启动日志和更好的用户体验。

### 传统启动方式

```bash
python main.py
```

## 启动日志对比

### 传统启动方式

传统方式会输出详细的SQL查询和日志信息，适合调试但不够简洁。

### 优雅启动方式

新的启动脚本将：
- 隐藏详细的SQL查询日志
- 只显示关键的服务器信息
- 将完整日志记录到文件中
- 提供更友好的启动界面

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
├── static/             # 静态文件
├── templates/          # 模板文件
├── tests/              # 测试代码
├── startup.py          # 优雅启动脚本
├── main.py             # 传统启动入口
└── requirements.txt    # 依赖包列表
```