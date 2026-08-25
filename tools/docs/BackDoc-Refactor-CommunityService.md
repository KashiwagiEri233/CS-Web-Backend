# BackDoc-Refactor-CommunityService：社区服务重构记录（Explanation · 为什么将 God Module 拆分为 5 个独立服务）

> 更新人：3yearsZ
> 更新日：2026-08-20
> 版本：1.0.1 · 七夕（Diátaxis E 类样板，统一解释类文档规范）
> Diátaxis：E（Explanation · 回答「为什么」，提供重构决策背景、过程与结论；不包含可执行步骤）
> 适用读者：后端开发者 / 架构师；已了解社区模块架构
> 变更触发：社区服务重构完成 → 本文档归档为历史记录

> **SSOT 分工声明**：
> - 本文档是「**社区服务（community_service.py）重构决策与执行记录**」的唯一权威（SSOT）。
> - 当前社区模块架构 → [BackDoc-01-Arch.md](BackDoc-01-Arch.md)（Arc42）。
> - 社区模块契约 → [BackDoc-ModuleContracts.md](BackDoc-ModuleContracts.md)（Reference）。
> - 重构前代码 → Git 历史（`community_service.py` 已于 2026-08-11 删除）。

> **治理红线**：
> - MUST NOT 在 `NotificationService` 中直接调用业务服务方法；通知 MUST 仅通过事件总线驱动
> - MUST NOT 在业务服务中反向 `import NotificationService`；通信 MUST 为单向（事件 → 通知）
> - MUST 在社区模块新增子域时遵循本文档的服务划分原则（单一职责、单向依赖）
> - MUST NOT 恢复 `community_service.py` God Module；如需合并 MUST 发起新的架构决策

---

## 1. 背景与动机：为什么是 God Module

### 1.1 问题描述

重构前的 `app/services/community_service.py` 是一个典型的 **God Module（上帝模块）**：

| 指标 | 数值 | 评估 |
|---|---|---|
| 文件行数 | 1,088 行 | 严重超标（单文件 > 400 行即预警） |
| 方法数量 | 57 个方法 | 横跨 posts/comments/reactions/favorites/follows/reports/series/notify/feed/enrich/interaction 等 11 个子域 |
| 测试耦合 | 单测需构造整类 | 覆盖面难以提升 |
| 依赖方向 | 通知、计数、关注关系散落同一类 | 无法独立部署/替换 |

### 1.2 痛点分析

| 痛点 | 影响 | 根因 |
|---|---|---|
| **认知负担高** | 新人难以定位、改动易波及无关路径 | 单文件承担全部社区逻辑 |
| **测试耦合严重** | 方法间互相调用，单测覆盖面低 | 缺乏明确的模块边界 |
| **依赖方向模糊** | 通知、计数反范式、关注关系混在一起 | 无分层/分包约束 |
| **与 AL-2 目标冲突** | AL-2 要求按子域拆 5 服务 | 当前结构不满足目标架构 |

### 1.3 重构决策

基于 Archi F1/F14 + Cody Q1（ER-15：God Module 治理）+ AL-2（按子域拆分）的联合建议，决定执行社区服务重构。

**重构原则**：
1. 按业务子域拆分，每个服务单一职责
2. 统一依赖方向（单向依赖，禁止循环）
3. `NotificationService` 仅订阅事件总线，不被业务服务直接调用
4. 每阶段保持对外 API 契约完全不变（OpenAPI baseline 零漂移）

---

## 2. 目标架构

### 2.1 5 服务划分

| 目标服务 | 职责边界 | 来源方法（示例） |
|---|---|---|
| **PostService** | 帖子 CRUD / 草稿 / 软删 / 浏览去重 / 系列归属 | `create_post` / `get_post` / `update_post` / `delete_post` / `list_posts` / `increment_view` / `_enrich_posts` |
| **CommentService** | 评论 CRUD / 楼中楼 / 编辑 / 删除 / 嵌套列表 | `create_comment` / `update_comment` / `delete_comment` / `list_nested_comments` |
| **ReactionService** | 点赞/收藏切换与计数/批量交互标记 | `toggle_like` / `toggle_favorite` / `get_reaction_status` / `list_user_favorites` + `CommunityInteractionRepository` |
| **FeedService** | 关注流/关注关系列表/计数聚合 | `list_following` / `list_followers` / `_format_follow_users` + `CommunityFollowRepository` |
| **NotificationService** | 通知生成与派发，**仅订阅事件总线** | 现有 `community_service` 内 notify 相关逻辑 |

### 2.2 关键边界（AL-2 核心约束）

`NotificationService` 不直接被业务服务调用，而是订阅领域事件（`CommentCreated` / `PostLiked` / `UserFollowed`），由事件总线驱动。业务服务只发事件，不感知通知实现，彻底解耦。

**依赖方向约束**：
- `PostService` / `CommentService` → `ReactionService`（查询互动标记）
- `FeedService` → `PostService`（取流内帖子）
- `NotificationService` 被事件总线驱动，不反向依赖业务服务
- **禁止** 业务服务 `import` `NotificationService` 的方法

---

## 3. 重构过程（Phase 0~4）

### Phase 0：加固基线

| 任务 | 状态 | 说明 |
|---|---|---|
| 确保 `community_service` 集成测试全绿 | ✅ 完成 | 作为行为对照 |
| 抽取纯函数/类型到 `_types` 或独立模块 | ✅ 完成 | 不改行为 |

### Phase 1：抽 NotificationService（最低风险）

通知逻辑最独立、无复杂事务耦合，优先拆出。

| 任务 | 状态 | 说明 |
|---|---|---|
| facade 将 notify 调用改为发领域事件 | ✅ 完成 | 调用方零感知 |
| `NotificationService` 订阅事件派发 | ✅ 完成 | 经事件总线驱动 |

### Phase 2：抽 ReactionService + FavoriteService

| 任务 | 状态 | 说明 |
|---|---|---|
| 复用 `CommunityInteractionRepository` | ✅ 完成 | `toggle_like` / `toggle_favorite` / `get_reaction_status` 迁移 |
| 反范式计数一致性验证 | ✅ 完成 | `like_count` / `favorite` 由事件或事务内维护 |

### Phase 3：抽 CommentService + PostService

| 任务 | 状态 | 说明 |
|---|---|---|
| 评论楼中楼、帖子草稿/软删/浏览去重迁移 | ✅ 完成 | 复用 `_enrich_posts` |
| 批量互动标记验证 | ✅ 完成 | 通过 ER-16 优化 |

### Phase 4：抽 FeedService + 最终清理

| 任务 | 状态 | 说明 |
|---|---|---|
| 关注流与关注列表迁移 | ✅ 完成 | 复用 ER-21 批量聚合优化 |
| 新建 CategoryService + ReportService + SeriesService | ✅ 完成 | 覆盖剩余子域 |
| 删除 `community_service.py` facade | ✅ **已删除**（2026-08-11） | 方法集差集 MISSING/EXTRA 均 NONE |
| API 注入切换（15 处） | ✅ 完成 | 路由层直接注入子服务 |

---

## 4. 验证与结果

### 4.1 验收标准达成

| 验收项 | 目标 | 实际 |
|---|---|---|
| `community_service.py` 不复存在 | < 100 行或删除 | ✅ **已删除** |
| 子服务单文件行数 | < 400 行 | ✅ 各子服务均在 400 行以内 |
| 子服务间循环依赖 | = 0 | ✅ 单向依赖验证通过 |
| 社区 integration 测试 | 全绿 | ✅ **432 passed** |
| OpenAPI 契约 | 零漂移 | ✅ 契约门禁通过 |
| 通知逻辑 | 经事件总线驱动 | ✅ 业务服务无直接 notify 依赖 |

### 4.2 不变量守住

| 不变量 | 说明 | 验证方式 |
|---|---|---|
| **API 契约不变** | 所有端点 path/method/权限/响应结构保持 | OpenAPI baseline diff 门禁（ER-04） |
| **反范式计数一致** | `reply_count` / `like_count` / `follower_count` 由事件/事务内维护 | 集成测试计数断言 |
| **事务边界不变** | `@transaction` / `db.commit()` 调用点迁移后等价 | 代码 diff + 事务测试 |
| **权限判定不变** | 社区端点权限（admin/owner/登录态）逻辑不变 | 权限集成测试 |

### 4.3 CI 闸门通过

| 闸门 | 结果 |
|---|---|
| 契约测试（OpenAPI diff 门禁 ER-04） | ✅ 通过 |
| 集成测试（社区 integration 套件） | ✅ 432 passed |
| 依赖方向 lint（禁止 NotificationService 被反向 import） | ✅ 通过 |

---

## 5. 结论

### 5.1 一句话结论

> **社区模块成功从 1,088 行的 God Module（`community_service.py`）拆分为 5 个独立服务（Post/Comment/Reaction+Favorite/Feed/Notification）+ 3 个辅助服务（Category/Report/Series），代码规模从 1 个 1,088 行文件变为 8 个 < 400 行的聚焦服务，集成测试 432 passed、OpenAPI 契约零漂移。**

### 5.2 经验总结

| 经验 | 说明 |
|---|---|
| **分阶段、每阶段可回滚** | Phase 0~4 每个阶段保持 API 契约不变，facade 转发保证调用方零改造 |
| **依赖方向是关键** | 明确单向依赖约束，防止拆分后重新形成循环 |
| **事件驱动解耦通知** | NotificationService 仅订阅事件，业务服务不感知通知实现，彻底解耦 |
| **不变量先行** | 在拆分前定义好 API 契约、计数一致性、事务边界等不变量，每个阶段验证 |

---

> ↩ **返回后端文档地图**：[BackDoc-01-Arch.md](BackDoc-01-Arch.md) · [BackDoc-ModuleContracts.md](BackDoc-ModuleContracts.md) · [BackDoc-03-Conv.md](BackDoc-03-Conv.md) · **架构决策**：[RootDoc-ADR.md](../../../docs/RootDoc-ADR.md)
