#!/usr/bin/env bash
# Ежедневный бэкап PostgreSQL: ./backup.sh  (cron: 30 4 * * * /home/kostya/CryptoBot/backup.sh)
# Хранит BACKUP_KEEP_DAYS дней (по умолчанию 14) в BACKUP_DIR (по умолчанию ~/backups/cryptobot).
# Восстановление: gunzip -c файл.sql.gz | psql "$DATABASE_URL"
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a

DIR="${BACKUP_DIR:-$HOME/backups/cryptobot}"
KEEP="${BACKUP_KEEP_DAYS:-14}"
mkdir -p "$DIR"
chmod 700 "$DIR"
FILE="$DIR/cryptobot-$(date +%Y%m%d-%H%M).sql.gz"

pg_dump --no-owner --no-privileges "$DATABASE_URL" | gzip -9 > "$FILE.tmp"
mv "$FILE.tmp" "$FILE"
chmod 600 "$FILE"
find "$DIR" -name 'cryptobot-*.sql.gz' -mtime +"$KEEP" -delete
echo "Backup OK: $FILE ($(du -h "$FILE" | cut -f1))"
