#!/bin/bash
# ============================================================
# Nanping 数据库备份脚本
# 建议添加到 crontab 每日运行：
#   0 3 * * * /opt/nanping/scripts/backup-db.sh >> /opt/nanping/backups/backup.log 2>&1
# ============================================================
set -e

APP_DIR="/opt/nanping"
BACKUP_DIR="$APP_DIR/backups"
DB_PATH="/var/lib/docker/volumes/nanping_nanping_data/_data/nanping.db"

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d-%H%M)
BACKUP_FILE="$BACKUP_DIR/nanping-$TIMESTAMP.db"

if [ -f "$DB_PATH" ]; then
    cp "$DB_PATH" "$BACKUP_FILE"
    SIZE=$(ls -lh "$BACKUP_FILE" | awk '{print $5}')
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 备份完成: $BACKUP_FILE ($SIZE)"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 错误: 数据库文件不存在 ($DB_PATH)"
    exit 1
fi

# 保留最近 7 天的备份
find "$BACKUP_DIR" -name "nanping-*.db" -mtime +7 -delete

# 统计
COUNT=$(find "$BACKUP_DIR" -name "nanping-*.db" | wc -l)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 当前保留 $COUNT 个备份文件"
