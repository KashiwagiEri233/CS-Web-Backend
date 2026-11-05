#!/usr/bin/env bash
# PostgreSQL 数据库备份脚本
#
# 用法：
#   ./backup_db.sh                          # 使用 .env 中的连接参数
#   ./backup_db.sh /custom/backup/dir       # 指定备份目录
#
# cron 示例（每日 03:00 全量备份，保留 14 天）：
#   0 3 * * * /path/to/CS-Web-Backend/tools/scripts/db/backup_db.sh >> /var/log/cs-backup.log 2>&1
#
# 恢复演练：
#   ./backup_db.sh --restore /path/to/backup.sql.gz
#
# 目标 RTO: 4h | 目标 RPO: 24h

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 脚本位于 tools/scripts/db/，仓库根为上三级（此前写 ../.. 只到 tools/，导致 .env 读不到）
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

# 加载环境变量
# 优先级：**显式传入的环境变量 > .env 文件**。
# 之前的写法用 `set -a; source .env`，会无条件覆盖调用方传入的 DATABASE_NAME 等，
# 导致「指定备份/恢复到别的库」静默失效——恢复目标被打回 .env 里的生产库名，
# 配合 --clean 就是「以为在演练、实际在洗生产库」的高危事故。
if [[ -f "$ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    # 跳过空行与注释；只认 KEY=VALUE
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*= ]] || continue
    key="${BASH_REMATCH[1]}"
    # 调用方已显式设置的同名变量优先，不覆盖
    if [[ -z "${!key:-}" ]]; then
      value="${line#*=}"
      value="${value%$'\r'}"                      # 兼容 CRLF
      value="${value%\"}"                          # 去包裹双引号
      value="${value#\"}"
      value="${value%\'}"                          # 去包裹单引号
      value="${value#\'}"
      export "$key=$value"
    fi
  done < "$ENV_FILE"
fi

DB_HOST="${DATABASE_HOST:-localhost}"
DB_PORT="${DATABASE_PORT:-5432}"
DB_NAME="${DATABASE_NAME:-domefff}"
DB_USER="${DATABASE_USER:-postgres}"
DB_PASSWORD="${DATABASE_PASSWORD:?请在 .env 中设置 DATABASE_PASSWORD}"

# ---- 子命令解析（必须先于任何目录创建：否则 `--restore` 会被当作备份目录 mkdir）----
MODE="backup"
RESTORE_FILE=""
if [[ "${1:-}" == "--restore" ]]; then
  MODE="restore"
  RESTORE_FILE="${2:?用法: backup_db.sh --restore <backup.sql.gz>}"
  shift 2
fi

BACKUP_DIR="${1:-${REPO_ROOT}/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"

# 恢复模式（归档为 custom 格式，必须用 pg_restore 读取，psql 无法解析二进制头）
if [[ "$MODE" == "restore" ]]; then
  if [[ ! -f "$RESTORE_FILE" ]]; then
    echo "[恢复] 归档不存在: $RESTORE_FILE" >&2
    exit 66
  fi
  # 安全闸（默认开启）：恢复到「生产库名」时要求显式确认，防演练误伤业务库。
  # 背景：--clean 会先 DROP 再重建对象，一旦目标库名解析错就是数据事故。
  if [[ "${RESTORE_ALLOW_OVERWRITE_PROD:-0}" != "1" ]]; then
    case "$DB_NAME" in
      *_tmp|*_probe|*_test|*_drill) ;;
      *)
        cat >&2 <<EOF
[恢复] 拒绝执行：目标库 "$DB_NAME" 不像演练库。
      生产/正式库恢复请显式确认：RESTORE_ALLOW_OVERWRITE_PROD=1 $0 --restore <归档>
      演练请用独立库名（如 ${DB_NAME}_drill）：先 CREATE DATABASE，再恢复。
EOF
        exit 65
        ;;
    esac
  fi
  echo "[恢复] 从 $RESTORE_FILE 恢复数据库 $DB_NAME ..."
  # 旧备份是 custom+gzip 的组合（见备份分支 --format=custom | gzip），先解压再 pg_restore。
  # --clean --if-exists：覆盖同名对象；--no-owner/--no-privileges 与备份参数对齐。
  set -o pipefail
  gunzip -c "$RESTORE_FILE" | PGPASSWORD="$DB_PASSWORD" pg_restore \
    -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    --no-owner --no-privileges --clean --if-exists --single-transaction --verbose
  RESTORE_RC=$?

  if [[ "$RESTORE_RC" -ne 0 ]]; then
    echo "[恢复] pg_restore 失败（exit $RESTORE_RC）：--single-transaction 已回滚，目标库保持恢复前状态" >&2
    exit "$RESTORE_RC"
  fi

  # 自增序列对齐：pg_restore 恢复数据行但不会推进 serial/identity 序列，
  # 不重置会让后续 INSERT 撞主键（典型症状：恢复后建用户报 duplicate key）。
  echo "[恢复] 对齐自增序列 ..."
  PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -v ON_ERROR_STOP=1 -q -t -A <<'SQL'
SELECT format(
  'SELECT setval(%L, GREATEST(COALESCE((SELECT MAX(%I) FROM %I), 0), 1));',
  pg_get_serial_sequence(c.table_name, c.column_name),
  c.column_name, c.table_name)
FROM information_schema.columns c
JOIN information_schema.tables t
  ON t.table_schema = c.table_schema AND t.table_name = c.table_name
WHERE c.table_schema = 'public'
  AND t.table_type = 'BASE TABLE'
  AND pg_get_serial_sequence(c.table_name, c.column_name) IS NOT NULL
\gexec
SQL

  echo "[恢复] 完成（序列已对齐）。"
  exit 0
fi

mkdir -p "$BACKUP_DIR"

# 备份模式
echo "[备份] 开始备份数据库 $DB_NAME -> $BACKUP_FILE"

PGPASSWORD="$DB_PASSWORD" pg_dump \
  -h "$DB_HOST" \
  -p "$DB_PORT" \
  -U "$DB_USER" \
  -d "$DB_NAME" \
  --no-owner \
  --no-privileges \
  --format=custom \
  --verbose \
  2>"${BACKUP_FILE%.sql.gz}.err" | gzip > "$BACKUP_FILE"

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[备份] 完成: $BACKUP_FILE ($BACKUP_SIZE)"

# 校验备份完整性（gzip -t 测试解压）
if gzip -t "$BACKUP_FILE" 2>/dev/null; then
  echo "[校验] gzip 完整性检查通过"
else
  echo "[警告] gzip 完整性检查失败，备份可能损坏: $BACKUP_FILE" >&2
  exit 1
fi

# 清理过期备份
DELETED=$(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -mtime +${RETENTION_DAYS} -print -delete | wc -l)
if [[ "$DELETED" -gt 0 ]]; then
  echo "[清理] 删除 $DELETED 个超过 ${RETENTION_DAYS} 天的旧备份"
fi

# 输出备份摘要
echo "[摘要] 数据库=$DB_NAME 文件=$BACKUP_FILE 大小=$BACKUP_SIZE 保留=${RETENTION_DAYS}天"
