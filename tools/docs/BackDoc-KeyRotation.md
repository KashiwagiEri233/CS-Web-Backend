# 密钥轮换 Runbook

> 适用范围：CS-Web-Backend 生产环境
> 触发条件：定期轮换（建议每 6 个月）/ 安全事件（疑似泄露）/ 人员变动

---

## 密钥清单

| 密钥 | 环境变量 | 轮换影响 | 紧急度 |
|------|----------|----------|--------|
| JWT 签名密钥 | `SECRET_KEY` | 全部 access/refresh token 失效，用户需重新登录 | 高 |
| TOTP 加密密钥 | `TOTP_ENCRYPTION_KEY` | 已存储的 2FA secret 无法解密，2FA 用户被锁 | 高 |
| 数据库密码 | `DATABASE_PASSWORD` | 需同步更新 PG 和应用配置 | 中 |
| 邮箱 IP 哈希密钥 | `FORUM_IP_HASH_SECRET` | 浏览去重计数重置（非安全风险） | 低 |

---

## JWT 签名密钥轮换（SECRET_KEY）

项目内置密钥轮换支持：`JWT_PREVIOUS_SECRET_KEYS`（逗号分隔的历史密钥列表）。

### 步骤

1. **准备新密钥**
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

2. **更新环境变量**（零停机）
   ```env
   # 把当前 SECRET_KEY 的值追加到历史列表
   JWT_PREVIOUS_SECRET_KEYS=<旧的SECRET_KEY值>
   # 设置新的 SECRET_KEY
   SECRET_KEY=<新生成的密钥>
   ```

3. **重启服务**（多 worker 逐个滚动重启）
   - 新 token 用新密钥签发
   - 旧 token 用 `JWT_PREVIOUS_SECRET_KEYS` 中的旧密钥校验（透明兼容）

4. **等待 access token 过期**（15 分钟）
   - 15 分钟后所有旧 access token 已过期
   - refresh token 轮换时也会用新密钥签发

5. **清理历史密钥**
   ```env
   # 确认无用户报告登录问题后，清空历史列表
   JWT_PREVIOUS_SECRET_KEYS=
   ```

6. **验证**
   - 确认新登录正常
   - 确认 15 分钟前的会话已自然过期
   - 检查日志无 token 校验异常

### 回滚

如新密钥有问题，把 `SECRET_KEY` 改回旧值，清空 `JWT_PREVIOUS_SECRET_KEYS`。

---

## TOTP 加密密钥轮换（TOTP_ENCRYPTION_KEY）

> **风险提示**：TOTP_ENCRYPTION_KEY 轮换会导致已加密存储的 2FA secret 全部不可解密。
> 当前版本不支持双密钥解密窗口期。轮换前必须让所有 2FA 用户重新设置。

### 步骤（需短暂维护窗口）

1. **通知所有 2FA 用户**：将进行维护，2FA 需要重新设置

2. **生成新密钥**
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

3. **更新环境变量**
   ```env
   TOTP_ENCRYPTION_KEY=<新生成的密钥>
   ```

4. **清除所有 2FA 记录**（数据库操作）
   ```sql
   -- 在维护窗口中执行
   TRUNCATE TABLE two_factor_auth;
   ```

5. **重启服务**

6. **通知用户重新设置 2FA**
   - 用户登录后需重新走 setup → confirm 流程

### 缓解方案（建议 1.1 实现）

实现「双密钥解密」窗口期（类似 JWT_PREVIOUS_SECRET_KEYS）：
- 新增 `TOTP_PREVIOUS_ENCRYPTION_KEYS` 配置
- 解密时先尝试当前密钥，失败后依次尝试历史密钥
- 轮换时：旧密钥加入历史列表 → 新密钥签发 → 后台任务用新密钥重新加密所有 secret → 清理历史列表

---

## 数据库密码轮换（DATABASE_PASSWORD）

1. **在 PostgreSQL 中设置新密码**
   ```sql
   ALTER USER postgres WITH PASSWORD '<新密码>';
   ```

2. **更新应用环境变量**
   ```env
   DATABASE_PASSWORD=<新密码>
   ```

3. **重启服务**

4. **验证** `/readyz` 返回 200

---

## 轮换记录模板

每次轮换后填写：

```
日期：YYYY-MM-DD
操作人：
轮换密钥：
旧密钥指纹（前 8 位 sha256）：
新密钥指纹（前 8 位 sha256）：
验证结果：
备注：
```
