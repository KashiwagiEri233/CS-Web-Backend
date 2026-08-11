# 社区服务重构史诗（ER-15 / AL-2）

> 状态：**规划中（safe-start）**。本文档仅立重构基线，不改动任何代码；实际拆解列为后续迭代（P2/P3），**不阻塞 0.9.9 / 1.0.0 收口**。
>
> 来源：工程保障团队 Archi F1/F14 + Cody Q1（ER-15，God Module）；AL-2 目标架构布局建议（按子域拆 5 服务，NotificationService 仅订阅事件总线）。

## 1. 问题描述（为什么是 God Module）

`app/services/community_service.py` 单类 **1088 行 / 57 个方法**，横跨 posts / comments / reactions / favorites / follows / reports / series / notify / feed / enrich / interaction 等多个子域。痛点：

- **认知负担高**：单文件承担全部社区逻辑，新人难以定位、改动易波及无关路径。
- **测试耦合**：方法间互相调用，单测需构造整类，覆盖面难以提升（见 ER-02/ER-11）。
- **依赖方向模糊**：通知、计数反范式、关注关系散落同一类，无法独立部署/替换。
- **与 AL-2 目标冲突**：AL-2 要求「community_service 按子域拆 Post/Comment/Reaction/Feed/Notification 5 服务，NotificationService 仅订阅事件总线」——当前结构不满足。

## 2. 目标架构

按业务子域拆分为 **5 个独立服务**，统一依赖方向（`CommunityService` 退化为外观 facade，最终删除）：

| 目标服务 | 职责边界 | 当前来源方法（示例） |
|---|---|---|
| `PostService` | 帖子 CRUD / 草稿 / 软删 / 浏览去重 / 系列归属 | `create_post` / `get_post` / `update_post` / `delete_post` / `list_posts` / `increment_view` / `_enrich_posts` |
| `CommentService` | 评论 CRUD / 楼中楼 / 编辑 / 删除 / 嵌套列表 | `create_comment` / `update_comment` / `delete_comment` / `list_nested_comments` |
| `ReactionService` | 点赞 / 收藏切换与计数 / 批量交互标记 | `toggle_like` / `toggle_favorite` / `get_reaction_status` / `list_user_favorites` + `CommunityInteractionRepository` |
| `FeedService` | 关注流 / 关注关系列表 / 计数聚合 | `list_following` / `list_followers` / `_format_follow_users` + `CommunityFollowRepository` |
| `NotificationService` | 通知生成与派发，**仅订阅事件总线** | 现有 `community_service` 内 notify 相关逻辑（评论/点赞/关注后的通知） |

**关键边界（AL-2）**：`NotificationService` 不直接被业务服务调用，而是订阅领域事件（如 `CommentCreated` / `PostLiked` / `UserFollowed`），由事件总线驱动。业务服务只发事件，不感知通知实现，彻底解耦。

## 3. 依赖方向与禁令

- 子服务之间**单向依赖**：`PostService` / `CommentService` → `ReactionService`（查询互动标记）；`FeedService` → `PostService`（取流内帖子）；`NotificationService` 被事件总线驱动，不反向依赖业务服务。
- **禁止**业务服务 `import` `NotificationService` 的方法（须经事件总线）。
- 跨服务数据访问仍走各自 `Repository`（已在 `app/repositories/community_repo.py` 按实体拆分，可直接复用）。

## 4. 迁移策略（分阶段、每阶段可回滚）

> 原则：每阶段保持对外 API 契约（OpenAPI 基线）**完全不变**；`CommunityService` 作为 facade 转发，调用方零改造；单阶段合入后再迁移下一阶段。

- **Phase 0 — 加固基线（先行）**
  - 确保 `community_service` 现有集成测试（见 `tools/tests/integration/test_phase4_community.py`）全绿，作为行为对照。
  - 抽取纯函数/类型到 `_types` 或独立模块，不改行为。
- **Phase 1 — 抽 `NotificationService`（最低风险）**
  - 通知逻辑最独立、无复杂事务耦合，优先拆出。
  - facade 将 notify 调用改为发领域事件；`NotificationService` 订阅事件派发。
- **Phase 2 — 抽 `ReactionService` + `FavoriteService`**
  - 复用 `CommunityInteractionRepository`；`toggle_like` / `toggle_favorite` / `get_reaction_status` 迁移。
  - 注意 `like_count` / `favorite` 反范式计数的一致性（见 §5 不变量）。
- **Phase 3 — 抽 `CommentService` + `PostService`**
  - 评论楼中楼、帖子草稿/软删/浏览去重迁移；`_enrich_posts` 归入 `PostService`（批量互动标记已通过 ER-16 优化）。
- **Phase 4 — 抽 `FeedService`**
  - 关注流与关注列表迁移（关注计数批量聚合已通过 ER-21 优化）；最后删除 `CommunityService` facade，调用方改指具体子服务。
  - ✅ **已完成（2026-08-11）**：新建 `FeedService`（关注 CRUD/列表/计数）+ `CategoryService` + `ReportService` + `SeriesService` 四服务；api 剩余 15 处注入切换；`app/services/community_service.py` 删除（方法集差集对比 MISSING/EXTRA 均 NONE）。**本史诗 Phase 0~4 全量落地**，AL-2 五服务（Post/Comment/Reaction+Favorite/Feed/Notification）闭环；全量 432 passed、OpenAPI 契约零漂移。

## 5. 必须守住的不变量

- **API 契约不变**：所有端点 path/method/权限/响应结构保持，OpenAPI 基线（`openapi.baseline.json`）比对零新增漂移（见 ER-04 契约门禁）。
- **反范式计数一致**：`reply_count` / `like_count` / `follower_count` 等由事件或事务内维护，迁移后不得出现计数偏差。
- **事务边界**：原 `@transaction` / `db.commit()` 调用点迁移后保持等价，避免跨服务长事务。
- **权限判定**：社区端点权限（admin/owner/登录态）逻辑不变，仅随服务迁移落地。

## 6. CI 闸门（每阶段合入前）

- 契约测试：OpenAPI diff 门禁（ER-04）—— 任何端点变更即失败。
- 集成测试：社区 integration 套件全绿（行为对照）。
- 依赖方向 lint：禁止 `NotificationService` 被业务服务反向 import、禁止子服务循环依赖（可用 `import-linter` 或自定义脚本，参照 AL-1 的 `check-bff-boundary.mjs` 思路）。

## 7. 验收标准（重构完成时）

- `community_service.py` 不复存在（或退化为 < 100 行的路由适配层）。✅ **已删除（Phase 4，2026-08-11）**
- 任一子服务单文件 < 400 行；子服务间循环依赖 = 0。
- 社区 integration 测试全绿，契约零漂移。
- 通知逻辑经事件总线驱动，业务服务无直接 notify 依赖。

## 8. 范围与排期

- **本轮（safe-start）**：仅本文档立基线，零代码改动。
- **后续迭代**：Phase 0~4 按上表推进，建议每个 Phase 独立 PR + 门禁；不阻塞 0.9.9 与 1.0.0 收口（属 P2/P3 架构优化）。
