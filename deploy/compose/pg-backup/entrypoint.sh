#!/usr/bin/env bash
# Generate a crontab from BACKUP_CRON, then hand off to cron in the
# foreground so docker logs capture stdout/stderr from each run.
set -euo pipefail

: "${BACKUP_CRON:=15 2 * * *}"

# Persist env-vars so cron child-jobs see them (cron strips the parent env).
{
  echo "POSTGRES_HOST=${POSTGRES_HOST}"
  echo "POSTGRES_USER=${POSTGRES_USER}"
  echo "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}"
  echo "POSTGRES_DB=${POSTGRES_DB}"
  echo "BACKUP_RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-14}"
  echo "PATH=/usr/local/bin:/usr/bin:/bin"
} > /etc/environment

cat <<EOF > /etc/cron.d/magister-backup
${BACKUP_CRON} root . /etc/environment; /usr/local/bin/backup.sh >> /var/log/pg-backup.log 2>&1
EOF
chmod 0644 /etc/cron.d/magister-backup
crontab /etc/cron.d/magister-backup

# Touch the log so tail -f works from the get-go.
mkdir -p /var/log && : > /var/log/pg-backup.log

echo "[pg-backup] cron schedule: ${BACKUP_CRON}"
# Run once on start so backups exist even if cron hasn't fired yet.
/usr/local/bin/backup.sh >> /var/log/pg-backup.log 2>&1 || true

# Exec cron in foreground; mirror its log to stdout for `docker logs`.
cron -f &
exec tail -F /var/log/pg-backup.log
