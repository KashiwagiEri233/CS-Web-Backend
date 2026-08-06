# SLO 与可观测性基线（1.0.0）

> 适用范围：CS-Web-Backend + CS-Web-Frontend
> 版本：1.0.0 起生效，后续版本按实际运行数据迭代

---

## 服务级别目标（SLO）

### 可用性

| 指标 | 目标 | 测量方式 |
|------|------|----------|
| API 可用性 | 99%（每月停机 ≤ 438 分钟） | `/health` + `/readyz` 探针成功率，按月统计 |
| 前端页面可用性 | 99% | 首页 HTTP 200 成功率 |

### 延迟

| 指标 | 目标 | 测量方式 |
|------|------|----------|
| API p95 延迟 | < 500ms | FastAPI 请求日志 `duration_ms` 字段 |
| API p99 延迟 | < 2000ms | 同上 |
| 前端首屏加载（LCP） | < 2.5s | 浏览器 Performance API（1.1 接入 RUM） |

### 数据持久性

| 指标 | 目标 | 测量方式 |
|------|------|----------|
| 数据库备份 RPO | ≤ 24h | 每日 03:00 cron 全量备份 |
| 数据库恢复 RTO | ≤ 4h | 从备份恢复到服务可用 |
| 备份保留 | 14 天 | `backup_db.sh` 自动清理过期文件 |

---

## 错误预算

月度错误预算 = 总分钟数 × (1 - SLO) = 43200 × 1% = **432 分钟/月**

错误预算耗尽时的行动：
- 冻结非紧急变更，集中精力修复稳定性问题
- 评估是否需要调整 SLO 目标（而非放松标准）

---

## 可观测性基线

### 日志

| 组件 | 格式 | 关键字段 |
|------|------|----------|
| 后端 | loguru JSON（prod profile） | timestamp, level, request_id, user_id, method, path, status, duration_ms |
| 前端 | pino NDJSON | timestamp, level, request_id, msg |

日志保留：文件轮转 10 MB × 30 天（后端），pino 日志按部署环境配置。

### 健康检查端点

| 端点 | 用途 | 检查内容 |
|------|------|----------|
| `GET /health` | liveness | 进程存活（浅检查） |
| `GET /readyz` | readiness | 数据库连通性，不通返回 503 |
| `GET /metrics/json` | 指标 | 请求数/延迟分布/错误率（需 system:monitor 权限） |
| `GET /status` | 详细状态 | 应用配置/连接池/版本（需 system:monitor 权限） |

### 告警规则（最小集）

以下告警通过日志监控或外部探针实现，1.0.0 不依赖 Prometheus：

| 告警 | 条件 | 级别 | 通知方式 |
|------|------|------|----------|
| 服务不可用 | `/health` 连续 3 次失败（间隔 10s） | P0 | 日志 + 邮件 |
| 数据库不可达 | `/readyz` 连续 2 次返回 503 | P0 | 日志 + 邮件 |
| 错误率飙升 | 5xx 占比 > 5%（5 分钟窗口） | P1 | 日志 |
| 备份失败 | `backup_db.sh` exit code ≠ 0 | P1 | cron 日志 |
| 磁盘空间不足 | 磁盘使用率 > 85% | P1 | 系统监控 |

### OpenTelemetry（可选增强）

1.0.0 默认关闭 OTel。如需启用：

```env
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4317
OTEL_SERVICE_NAME=cs-web-backend
```

启用后自动埋点 FastAPI / SQLAlchemy / Redis，traces + metrics 经 OTLP 导出。

---

## 运维巡检清单

每日：
- 确认备份脚本执行成功（检查 `backups/` 目录最新文件）
- 浏览错误日志中的 ERROR 级别条目

每周：
- 检查磁盘空间和日志文件大小
- 验证 `/readyz` 响应正常

每月：
- 评估 SLO 达成情况
- 检查错误预算消耗
- 评估是否需要调整 SLO 目标

每季度：
- 执行一次数据库恢复演练
- 审查告警规则有效性
