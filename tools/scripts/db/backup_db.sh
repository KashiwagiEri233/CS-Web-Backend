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
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

# 加载环境变量
if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

DB_HOST="${DATABASE_HOST:-localhost}"
DB_PORT="${DATABASE_PORT:-5432}"
DB_NAME="${DATABASE_NAME:-domefff}"
DB_USER="${DATABASE_USER:-postgres}"
DB_PASSWORD="${DATABASE_PASSWORD:?请在 .env 中设置 DATABASE_PASSWORD}"

BACKUP_DIR="${1:-${REPO_ROOT}/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

# 恢复模式
if [[ "${1:-}" == "--restore" ]]; then
  RESTORE_FILE="${2:?用法: backup_db.sh --restore <backup.sql.gz>}"
  echo "[恢复] 从 $RESTORE_FILE 恢复数据库 $DB_NAME ..."
  PGPASSWORD="$DB_PASSWORD" gunzip -c "$RESTORE_FILE" | \
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1
  echo "[恢复] 完成。"
  exit 0
fi

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
