# Installation: Vita Brevis Cockpit — End-to-End

Vom leeren Ubuntu 24.04 LTS bis zum lauffähigen Cockpit für das Vita-Brevis-Ops-Team.

**Geschätzter Zeitaufwand:** 20 Minuten

> **TL;DR:** Wenn du es eilig hast: `scripts/install-cockpit.sh` auf einem frischen Ubuntu-Host ausführen. Dieses Runbook ist die Langform mit Erklärungen.

---

## 0. Was du vorher bereit haben musst

| Item | Wozu |
|---|---|
| Ubuntu-VM 24.04 LTS, ≥ 1 vCPU, ≥ 2 GB RAM, ≥ 10 GB Disk | Compose-Stack |
| Internes DNS (z.B. `cockpit.internal`) | Wir machen kein TLS für intern |
| VPN- oder Tailscale-Zugriff für das Ops-Team | Cockpit ist **nicht** öffentlich |
| SSH-Zugriff zum Ops-Host | Deploy |

⚠ **Niemals** das Cockpit auf einem Host betreiben, der von außen erreichbar ist — die Auth ist auf interne Trust-Boundary ausgelegt.

---

## 1. System vorbereiten

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git

# Docker installieren (offizielles APT-Repo)
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker
```

---

## 2. Code holen

```bash
sudo mkdir -p /opt/cockpit
sudo chown $USER:$USER /opt/cockpit
git clone https://github.com/vita-brevis-gmbh/magister.git /opt/cockpit/src
cd /opt/cockpit/src/cockpit/deploy
```

---

## 3. Secrets generieren

```bash
BOOTSTRAP_TOKEN=$(openssl rand -base64 32 | tr -d '/+=' | head -c 40)
echo "COCKPIT_BOOTSTRAP_TOKEN=$BOOTSTRAP_TOKEN" > /opt/cockpit/src/cockpit/deploy/.env
chmod 600 /opt/cockpit/src/cockpit/deploy/.env

# In 1Password ablegen (oder Vault deiner Wahl)
echo ""
echo "↓ Diesen Token jetzt in 1Password speichern:"
echo "$BOOTSTRAP_TOKEN"
```

---

## 4. Stack starten

```bash
cd /opt/cockpit/src/cockpit/deploy
docker compose up -d
```

Das Compose-File startet:
- `postgres` (Port 5433 lokal)
- `api` (Port 8001 lokal)

Frontend wird im aktuellen Stand separat per `vite build` + statischem Hosting deployed (folgt in M5.2 als Compose-Service).

---

## 5. Datenbank initialisieren

```bash
docker compose exec api alembic upgrade head
```

Erwartete Ausgabe:

```
INFO  [alembic.runtime.migration] Running upgrade  -> 0001_initial
INFO  [alembic.runtime.migration] Running upgrade 0001_initial -> 0002_update_requests
INFO  [alembic.runtime.migration] Running upgrade 0002_update_requests -> 0003_service_tokens
```

---

## 6. Smoke-Test

```bash
curl -sf http://localhost:8001/api/health
# {"status":"ok"}

curl -sf -H "Authorization: Bearer $BOOTSTRAP_TOKEN" http://localhost:8001/api/instances
# []
```

---

## 7. Ersten Service-Token erzeugen

Der Bootstrap-Token bleibt Break-Glass-Credential. Für den Alltag erstellen wir per Bootstrap-Token einen rotierenden Service-Token:

```bash
/opt/cockpit/src/scripts/bootstrap-cockpit-token.sh \
  --url http://localhost:8001 \
  --bootstrap-token "$BOOTSTRAP_TOKEN" \
  --description "ops-team-default" \
  --ttl-days 90
```

Der ausgegebene Token wird **nur einmal** angezeigt — direkt im 1Password speichern.

---

## 8. Erste Magister-Instanz registrieren

```bash
SERVICE_TOKEN=<dein-service-token>

curl -sf -X POST http://localhost:8001/api/instances \
  -H "Authorization: Bearer $SERVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "schule-x",
    "display_name": "Primarschule X",
    "base_url": "https://magister.schule-x.ch",
    "channel": "stable"
  }'
```

Innerhalb 60 Sekunden pollt das Cockpit `https://magister.schule-x.ch/api/healthz` und füllt `deployed_version` + `last_health_status`.

---

## 9. (Optional) Update-Runner installieren

Wenn das Ops-Team auch automatisierte Updates via Cockpit triggern soll, jetzt den Runner installieren — siehe [`cockpit-update-runner.md`](cockpit-update-runner.md).

---

## 10. Backup-Job einrichten

```bash
sudo tee /etc/cron.daily/cockpit-backup <<'EOF'
#!/bin/bash
set -e
cd /opt/cockpit/src/cockpit/deploy
mkdir -p /backup
docker compose exec -T postgres pg_dump -U cockpit cockpit \
  | gzip > /backup/cockpit-$(date +%Y%m%d).sql.gz
find /backup -name 'cockpit-*.sql.gz' -mtime +30 -delete
EOF
sudo chmod +x /etc/cron.daily/cockpit-backup
```

---

## Häufige Fehler

| Fehler | Ursache | Fix |
|---|---|---|
| `curl: (7) Failed to connect to localhost port 8001` | API noch nicht hochgefahren | `docker compose logs api` |
| `401 missing bearer token` | Authorization-Header fehlt | `-H "Authorization: Bearer $TOKEN"` |
| `403 invalid token` | Token falsch, abgelaufen oder revoked | Im 1Password nachschauen oder neu erzeugen |
| `last_health_status=unreachable` | Cockpit kann Magister-Host nicht erreichen | Firewall / DNS / Magister-Container prüfen |

---

## Nach dem Setup

- **Backup**: täglich (siehe §10)
- **Token-Rotation**: alle 90 Tage neue Service-Tokens via `bootstrap-cockpit-token.sh`
- **Updates des Cockpits selbst**: `cd /opt/cockpit/src && git pull && cd cockpit/deploy && docker compose pull && docker compose up -d && docker compose exec api alembic upgrade head`
