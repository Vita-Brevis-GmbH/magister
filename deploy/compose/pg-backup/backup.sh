#!/usr/bin/env bash
# Daily pg_dump → /var/backups/magister/<date>.sql.gz with retention pruning.
set -euo pipefail

: "${POSTGRES_HOST:?}"
: "${POSTGRES_USER:?}"
: "${POSTGRES_PASSWORD:?}"
: "${POSTGRES_DB:?}"
: "${BACKUP_RETENTION_DAYS:=14}"

BACKUP_DIR=/var/backups/magister
mkdir -p "$BACKUP_DIR"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="${BACKUP_DIR}/${POSTGRES_DB}-${stamp}.sql.gz"

export PGPASSWORD="$POSTGRES_PASSWORD"
echo "[pg-backup] starting dump: ${out}"
pg_dump --host="$POSTGRES_HOST" --username="$POSTGRES_USER" \
        --dbname="$POSTGRES_DB" --no-owner --no-privileges --format=plain \
        | gzip -9 > "$out"

# Best-effort retention: drop *.sql.gz older than RETENTION days.
find "$BACKUP_DIR" -type f -name "*.sql.gz" -mtime "+${BACKUP_RETENTION_DAYS}" -print -delete

echo "[pg-backup] done"
