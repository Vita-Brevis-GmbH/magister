FROM python:3.12-slim AS builder
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml ./
RUN uv pip install --system --no-cache .

FROM python:3.12-slim

# Sicherung und Rückspielung rufen vier externe Programme auf:
# `pg_dump`, `pg_restore` (services/backup.py, services/restore.py) und `age`
# für die Verschlüsselung (ADR-0016 D9). Ohne sie bricht die Konsole mit
# „pg_dump ist nicht installiert" ab — genau so ist es auf dem Dev-Host
# aufgefallen, nachdem die Prüfung im Code stand, die Werkzeuge im Bild aber
# nicht.
#
# Warum PGDG und nicht Debian: bookworm liefert PostgreSQL 15. Ein `pg_dump`
# 15 verweigert einen Server 16 („server version: 16.x; pg_dump version:
# 15.x — aborting"), und der Server IST 16 (docker-compose.yml). Das
# Hauptversions-Paar muss stimmen, es gibt keine Nachsicht. PGDG ist dabei
# weiterhin ein apt-Repository und kein heruntergeladenes Release: das Bild
# bekommt seine Sicherheitsaktualisierungen wie alles andere auch.
ARG PG_MAJOR=16
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg; \
    install -d /usr/share/postgresql-common/pgdg; \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
http://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends "postgresql-client-${PG_MAJOR}" age; \
    apt-get purge -y --auto-remove curl gnupg; \
    rm -rf /var/lib/apt/lists/*; \
    # Der Beweis gehört in den Bau und nicht in die erste Sicherung beim
    # Kunden: fehlt eines der vier Programme, scheitert hier das Image.
    pg_dump --version; \
    pg_restore --version; \
    age --version; \
    test "$(pg_dump --version | grep -oE '[0-9]+' | head -1)" = "${PG_MAJOR}"

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY cockpit_api ./cockpit_api
COPY alembic ./alembic
COPY alembic.ini ./
EXPOSE 8000
CMD ["uvicorn", "cockpit_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
