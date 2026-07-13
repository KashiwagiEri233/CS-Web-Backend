# 文档

每个模块一篇深入文档（描述 + 接口），**按"系统级 / 业务模块级"两层分类**——与错误码、异常体系
采用同一套"框架级 vs 业务级"的划分哲学（见 `AGENTS.md`）。顶层 `ARCHITECTURE.md` / `CONVENTIONS.md`
讲全局；本目录讲单个模块的细节。

```
docs/
├── README.md              # 本文件：分类约定 + 文档模板 + 索引
├── system/                # 系统级：框架/基础设施，与具体业务无关
│   ├── exception_handling.md   # 异常体系（自定义异常 + 全局处理器 + 中间件）
│   ├── observability.md        # 可观测性（OpenTelemetry traces/metrics）
│   ├── lifecycle.md            # 启动/关闭任务注册表（lifecycle registry）
│   └── queue.md                # 异步任务队列（arq，可选/可删除模块）
└── modules/               # 业务模块级：与具体业务实体绑定
    ├── auth.md            # 认证（登录/注册/刷新/登出）
    ├── users.md           # 用户管理（CRUD）
    ├── rbac.md            # 角色 / 权限 / 分配 / 校验
    └── audit.md           # 审计日志查询
```

## 分类标准（一篇文档放哪？）

| 类别 | 判据 | 对应代码大致位置 | 例 |
|---|---|---|---|
| **系统级** `docs/system/` | 与具体业务实体无关的框架/基础设施能力，换个项目也能复用 | `app/core/`、`app/middleware/`、`app/database.py` | 异常体系、可观测性、限流、缓存、日志、认证安全原语、DB 会话 |
| **业务模块级** `docs/modules/` | 与具体业务实体（用户、角色…）绑定的功能 | `app/api/v1/`、`app/services/`、`app/repositories/`、`app/models/` | 认证、用户管理、RBAC |

> 边界判断与「错误码归属」一致：与 HTTP/通用语义绑定的是系统级；与业务实体绑定的是业务模块级。
> 拿不准时问一句"换一个完全不同的项目，这块还用得上吗？"——用得上 → 系统级。

## 约定（新增模块必须同步文档）

- **加业务模块**（走 `AGENTS.md` 的「加一个 API 资源」配方）时，**必须**在 `docs/modules/` 建一篇同名文档；
  加系统级能力时建在 `docs/system/`。缺哪层目录建哪层。
- 文档文件名 = 模块名（如 `auth.md`），与 `app/api/v1/<name>.py` / 业务域名对应。
- 每篇文档**必须含"接口"一节**（API 端点表或公共函数/类签名）——这是后期维护的对照表，不可省。
- 接口表只记**契约**（method/path/权限/用途），字段细节**指向 `app/schemas/<x>.py`**，不在文档里重抄，
  避免与代码漂移。
- 文档与代码一同改：改了端点/签名/配置项，对应文档同 PR 更新（见下方检查清单）。

## 文档模板

新建模块文档时复制以下骨架（按需删减，但"概述 / 接口 / 测试"三节必留）：

```markdown
# <模块名>

## 概述
一句话定位 + 职责边界（这个模块负责什么、不负责什么）。

## 接口
### API 端点（业务模块级）
| Method | Path | 权限 | 说明 |
|---|---|---|---|
| ... | ... | ... | ... |
入/出参 schema 见 `app/schemas/<x>.py`。

### 公共函数 / 类（系统级或被复用的能力）
| 符号 | 签名 | 用途 |
|---|---|---|

## 配置
相关 `Settings` 字段（`app/core/config.py`）及默认值、降级行为。

## 依赖与协作
依赖的 service / repository / core 能力；被谁调用。

## 降级与不变量
（如适用）故障降级策略、必须守住的约束。

## 测试
对应 `tests/<...>` 路径与覆盖点。

## 扩展指引
怎么在此模块上加东西、有哪些坑。
```

## 索引

### 系统级（`docs/system/`）
| 文档 | 覆盖代码 | 状态 |
|---|---|---|
| [exception_handling.md](system/exception_handling.md) | `app/core/exceptions/` | ✅ |
| [observability.md](system/observability.md) | `app/core/observability.py`、运维端点 | ✅ |
| [lifecycle.md](system/lifecycle.md) | `app/core/lifecycle/`（启动/关闭任务注册表） | ✅ |
| [queue.md](system/queue.md) | `app/core/queue/`（可选模块，arq） | ✅ |
| _rate_limit.md_ | `app/core/rate_limit/`、`app/middleware/rate_limit.py` | ⬜ 待补 |
| _cache.md_ | `app/core/cache/` | ⬜ 待补 |
| _security_auth.md_ | `app/core/security.py`、`app/middleware/rbac.py` | ⬜ 待补 |
| _logging.md_ | `app/core/loguru_logger/` | ⬜ 待补 |
| _database.md_ | `app/database.py` | ⬜ 待补 |

### 业务模块级（`docs/modules/`）
| 文档 | 覆盖代码 | 状态 |
|---|---|---|
| [auth.md](modules/auth.md) | `app/api/v1/auth.py`、`app/services/auth_service.py` | ✅ |
| [users.md](modules/users.md) | `app/api/v1/users.py`、`app/services/user_service.py` | ✅ |
| [rbac.md](modules/rbac.md) | `app/api/v1/rbac/`、`app/services/rbac_service.py` | ✅ |
| [audit.md](modules/audit.md) | `app/api/v1/audit.py`、`app/services/audit_service.py` | ✅ |

> ⬜ 待补项是已存在的系统能力但文档未写——欢迎按模板补齐，不要让索引与实际能力脱节。

## 提交前检查清单
- [ ] 新增 API 端点 → 对应 `docs/modules/<x>.md` 的接口表已更新
- [ ] 新增/改名公共函数或配置项 → 对应文档已更新
- [ ] 新建模块 → 已建文档并登记到上方索引表
- [ ] 文档里的 schema/字段是**指向** `app/schemas/`，而非重抄
