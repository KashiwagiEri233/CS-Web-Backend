# 文档

本目录是仓库的**全部开发文档**，已扁平化：所有现行文档平铺在 `docs/` 根级（无嵌套目录），按主题组织。

```
docs/
├── README.md              # 本文件：文档索引 + 约定 + 模板
├── onboarding.md          # 新手引导：快速开始/目录/开发工作流/常见坑
├── architecture.md        # 系统架构总览（分层/中间件链/生命周期/不变量）
├── conventions.md         # 编码规范、命名、质量红线
├── security.md            # 安全与防护：鉴权/异常处理/请求限流
├── infrastructure.md      # 运行基础设施：可观测性/数据库/生命周期/队列/缓存
├── modules.md             # 业务模块：认证/用户/RBAC/审计
├── MIGRATION_VERIFICATION.md  # 迁移验证指南（Linux/PG 环境）
└── archive.md             # 历史归档：迁移计划 + 特性设计稿（不作现行方案）
```

## 一篇文档放哪？

| 文档 | 放什么内容 |
|---|---|
| `architecture.md` | 系统级架构：分层、中间件链、请求生命周期、关键不变量 |
| `security.md` | 鉴权（JWT/密码/黑名单）、异常体系、请求限流 |
| `infrastructure.md` | 日志 + 追踪/指标（可观测）、数据库/事务、启动关闭任务、队列、缓存 |
| `modules.md` | 业务模块 API：认证 / 用户 / RBAC / 审计 |
| `conventions.md` | 编码规范、命名、质量红线、安全/错误处理约定 |
| `MIGRATION_VERIFICATION.md` | Linux/PG 环境迁移验证指南 |

> 拿不准放哪时问一句"换一个完全不同的项目，这块还用得上吗？"——用得上 → 系统级（`security.md`/`infrastructure.md`）；
> 与具体业务实体（用户/角色…）绑定 → `modules.md`。

## 约定（新增模块必须同步文档）

- 改代码（端点/签名/配置项/模块）时，**对应文档同 PR 更新**（见下方检查清单）。
- 每篇文档的**接口一节**是后期维护对照表，不可省。
- 接口表只记**契约**（method/path/权限/用途），字段细节**指向 `app/schemas/<x>.py`**，不在文档重抄，避免漂移。
- 新增**业务模块**时，在 `modules.md` 对应节追加（或在 `docs/modules/<name>.md` 新建后登记到本文件索引）。

## 文档模板

新建模块文档时复制以下骨架（"概述 / 接口 / 测试"三节必留）：

```markdown
# <模块名>

## 概述
一句话定位 + 职责边界（负责什么、不负责什么）。

## 接口
| Method | Path | 权限 | 说明 |
|---|---|---|---|
| ... | ... | ... | ... |
schema 见 `app/schemas/<x>.py`。

## 配置
相关 `Settings` 字段（`app/core/config.py`）及默认值、降级行为。

## 降级与不变量
故障降级策略、必须守住的约束。

## 测试
对应 `tests/<...>` 路径与覆盖点。

## 扩展指引
怎么在此模块上加东西、有哪些坑。
```

## 索引

### 全局文档
| 文档 | 说明 |
|---|---|
| [onboarding.md](onboarding.md) | 新手引导：快速开始、目录、开发工作流、常见坑（新贡献者从这里入手） |
| [architecture.md](architecture.md) | 系统架构总览（分层、目录结构、扩展配方） |
| [conventions.md](conventions.md) | 编码规范、命名、质量红线、安全/错误处理约定 |

### 系统能力
| 文档 | 覆盖代码 |
|---|---|
| [security.md](security.md) | 鉴权：`app/core/security.py`、`security_blacklist.py`、`middleware/rbac.py`、`password_compat.py`；异常：`app/core/exceptions/`；限流：`app/core/rate_limit/`、`middleware/rate_limit.py` |
| [infrastructure.md](infrastructure.md) | 日志：`app/core/loguru_logger/`；OTel：`app/core/observability.py`；DB：`app/database.py`；生命周期：`app/core/lifecycle/`；队列：`app/core/queue/`；缓存：`app/core/cache/`；运维端点 `/health` `/readyz` `/metrics/json` `/status` |

### 业务模块
| 文档 | 覆盖代码 |
|---|---|
| [modules.md](modules.md) | 认证：`app/api/v1/auth.py`、`services/auth_service.py`；用户：`app/api/v1/users.py`、`profile.py`；RBAC：`app/api/v1/rbac/`；审计：`app/api/v1/audit.py` |

### 迁移相关
| 文档 | 说明 |
|---|---|
| [MIGRATION_VERIFICATION.md](MIGRATION_VERIFICATION.md) | 数据层迁移的 Linux/PG 环境验证指南 |

### 历史归档
已完成特性的迁移计划与设计稿，仅作演进痕迹保留，**不作现行方案**。当前能力以根级正式文档为准。

| 文档 | 对应实现 | 状态 |
|---|---|---|
| [archive.md](archive.md) | 前后端分离迁移计划 + 异常/日志系统设计稿 | ✅ 归档 |

## 提交前检查清单
- [ ] 新增/修改 API 端点 → 对应文档（`security.md`/`infrastructure.md`/`modules.md`）接口表已更新
- [ ] 新增/改名公共函数或配置项 → 对应文档已更新
- [ ] 新建模块 → `modules.md` 登记或新建 `docs/modules/<name>.md` 并登记到本索引
- [ ] 文档里的 schema/字段是**指向** `app/schemas/`，而非重抄
