# Runbook: Disaster Recovery

**Ziel-RTO:** 4 Stunden (Total Loss eines Magister-Hosts)
**Ziel-RPO:** 24 Stunden (täglich `pg_dump` via Cron)

---

## Backup-Inventar (was muss überleben)

| Asset | Wo? | Backup-Strategie |
|---|---|---|
| PostgreSQL-DB (Magister) | `magister-db`-Volume | Tägliches `pg_dump` → S3/Backblaze, verschlüsselt mit `age` |
| `.env` (Secrets: `MAGISTER_AUDIT_KEY`, OIDC-Client-Secret, AD-Bind-PW) | `/etc/magister/.env` | Vault (1Password Business) — **nicht** im DB-Backup |
| Caddy-Daten (TLS-Zertifikate) | `caddy_data`-Volume | Werden automatisch neu ausgestellt — kein Backup nötig |
| Docker-Compose-Definition + Image-Tag | Git-Repo + Cockpit `instances.deployed_version` | Aus Git wiederherstellbar |

⚠ **Reihenfolge ist nicht beliebig**: ohne `MAGISTER_AUDIT_KEY` ist die DB nutzlos (Audit-Payloads `pgcrypto`-verschlüsselt).

---

## Recovery — Total Loss

### 1. Neuen Host bereitstellen

```bash
# Standard-Ubuntu-LTS + Docker, gem. install-ubuntu.md
ssh root@new-host
apt update && apt install -y docker.io docker-compose-plugin age
```

### 2. Secrets wiederherstellen

```bash
# Aus 1Password
op read "op://Vita-Brevis/magister-<schulträger>-env" > /etc/magister/.env
chmod 600 /etc/magister/.env
```

### 3. Backup ziehen + entschlüsseln

```bash
aws s3 cp s3://vb-magister-backups/<schulträger>/latest.sql.age /tmp/db.sql.age
age -d -i /etc/magister/age.key /tmp/db.sql.age > /tmp/db.sql
```

### 4. Compose-Stack starten

```bash
git clone https://github.com/vita-brevis-gmbh/magister.git /opt/magister
cd /opt/magister/deploy/compose
docker compose up -d postgres
# Warten bis postgres bereit
until docker compose exec -T postgres pg_isready -U magister; do sleep 2; done
```

### 5. DB einspielen

```bash
docker compose exec -T postgres psql -U postgres <<SQL
CREATE DATABASE magister OWNER magister;
SQL
cat /tmp/db.sql | docker compose exec -T postgres psql -U magister magister
docker compose run --rm api alembic upgrade head
docker compose up -d
```

### 6. Smoke-Test

```bash
curl -sf https://<host>/api/healthz | jq .
# version sollte zur letzten bekannten deployed_version passen (siehe Cockpit)
```

### 7. Cockpit informieren

Cockpit pollt automatisch — innerhalb von 60s steht die Instanz wieder auf `ok`.
Bei IP-Wechsel: `PATCH /instances/{id}` mit neuer `base_url`.

---

## Recovery — Nur DB-Korruption

```bash
# Stack stoppen
docker compose stop api web
# Snapshot wiederherstellen (siehe oben Schritt 5)
# Stack starten
docker compose start api web
```

---

## Recovery — Audit-Key verloren

**Schwerwiegend**: ohne `MAGISTER_AUDIT_KEY` sind alle bisherigen Audit-Payloads unentschlüsselbar.

1. Mit neuem Key starten (DB-Daten bleiben, aber alle alten Events sind nur als Hash-Stub lesbar)
2. revDSG-Pflicht: Datenschutzbeauftragten informieren — Audit-Lücke dokumentieren
3. Forensik vorbei — Backups vom Audit-Key prüfen

---

## Übungs-Plan

- **Quartalsweise** Recovery-Drill auf Staging-Host
- Ergebnis dokumentieren in `docs/security/dr-drill-<YYYY-QN>.md`
- RTO/RPO-Werte aktualisieren bei Abweichung
