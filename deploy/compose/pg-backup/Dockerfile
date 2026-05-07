# Tiny sidecar that runs pg_dump on a cron schedule and prunes old dumps.
# Uses the postgres:16 image purely for the matching pg_dump binary.

FROM postgres:16

RUN apt-get update \
 && apt-get install -y --no-install-recommends cron gzip \
 && rm -rf /var/lib/apt/lists/*

COPY backup.sh /usr/local/bin/backup.sh
COPY entrypoint.sh /usr/local/bin/pg-backup-entrypoint.sh
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/pg-backup-entrypoint.sh

VOLUME ["/var/backups/magister"]

ENTRYPOINT ["/usr/local/bin/pg-backup-entrypoint.sh"]
