# Runbook: Cockpit Update-Runner

Der Update-Runner ist ein internes Vita-Brevis-Tool, das pending `update_requests` aus dem Cockpit abholt und auf den Ziel-Magister-Instanzen via SSH ausführt.

## Voraussetzungen

- Ein dedizierter Ops-Host (z.B. `ops.internal`) mit Netzwerkzugriff auf:
  - Cockpit-API (intern, hinter VPN)
  - SSH zu allen verwalteten Magister-Instanzen (Port 22)
- SSH-Key des Runner-Users in `authorized_keys` jedes Magister-Hosts unter dem User `magister-ops` (sudo für `docker compose` und `pg_dump`)
- Auf jedem Magister-Host:
  - `/opt/magister/` mit `docker-compose.yml`
  - `/backup/` Verzeichnis (für `pg_dump`-Snapshots)
  - Image-Tag im Compose über `${IMAGE_TAG}` parametrisiert

## Setup auf dem Ops-Host

```bash
sudo useradd -r -d /opt/cockpit-runner -s /usr/sbin/nologin cockpit-runner
sudo mkdir -p /opt/cockpit-runner /etc/cockpit-runner
sudo chown -R cockpit-runner:cockpit-runner /opt/cockpit-runner

# Code deployen
sudo -u cockpit-runner git clone https://github.com/vita-brevis-gmbh/magister.git /tmp/magister
sudo -u cockpit-runner cp -r /tmp/magister/cockpit/runner /opt/cockpit-runner/src
sudo -u cockpit-runner python3.12 -m venv /opt/cockpit-runner/.venv
sudo -u cockpit-runner /opt/cockpit-runner/.venv/bin/pip install /opt/cockpit-runner/src

# Konfiguration
sudo tee /etc/cockpit-runner/cockpit-runner.env <<EOF
RUNNER_COCKPIT_URL=http://cockpit.internal:8001
RUNNER_COCKPIT_TOKEN=<cockpit-bootstrap-token>
RUNNER_POLL_INTERVAL_S=30
RUNNER_SSH_USER=magister-ops
RUNNER_DRY_RUN=false
EOF
sudo chmod 600 /etc/cockpit-runner/cockpit-runner.env

# systemd
sudo cp /opt/cockpit-runner/src/systemd/cockpit-runner.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cockpit-runner
```

## Bedienung

- **Update einplanen:** Im Cockpit-UI „Update einplanen" pro Instanz (oder via `POST /api/update-requests/instance/{id}`)
- **Abbrechen:** Nur solange `pending`. Wenn der Runner schon `in_progress` gesetzt hat → Update läuft durch oder schlägt fehl.
- **Logs:** `journalctl -u cockpit-runner -f`

## Was tut der Runner pro Request

1. `GET /api/update-requests/next` (atomic claim mit `SELECT ... FOR UPDATE SKIP LOCKED`)
2. `ssh magister-ops@<host>` → `pg_dump | gzip > /backup/before-<version>-<timestamp>.sql.gz`
3. `IMAGE_TAG=<version> docker compose pull`
4. `IMAGE_TAG=<version> docker compose up -d`
5. Smoke-Test gegen `https://<host>/api/healthz`, Vergleich `version`
6. Erfolg → `POST /complete` (Cockpit aktualisiert `deployed_version`)
7. Fehler → `POST /fail` mit Fehlertext; Snapshot bleibt liegen für manuellen Roll-Back

## Roll-Back

```bash
ssh magister-ops@<host>
cd /opt/magister
# Snapshot wiederherstellen
gunzip -c /backup/before-<version>-<ts>.sql.gz | docker compose exec -T postgres psql -U magister magister
# Altes Image-Tag pinnen
IMAGE_TAG=<old-version> docker compose up -d
```

## Bekannte Einschränkungen

- Kein Multi-Region-Failover (M4-future)
- Kein automatischer Roll-Back bei Fehler — bewusst manuell, weil DB-Migrationen in seltenen Fällen nicht rückwärtskompatibel sind
- Pre-snapshot ist `pg_dump`, kein PITR — kürzeste Restore-Zeit ~5 min bei 50k Audit-Events
