# Upgrade-Runbook: M1 → M2

**Gilt für:** Magister-Instanzen auf M1-Stand (ab Git-Tag `v0.1.x`)  
**Ziel-Version:** M2 (`v0.2.x`)  
**Aufwand:** ~15 Minuten Downtime

---

## Was ist neu in M2

| Feature | Endpoint / Route |
|---|---|
| AD User Enable/Disable | `PATCH /users/{guid}/status` |
| Bulk-Schüler-Zuteilung | `POST /classes/{id}/students/bulk` |
| Schuljahres-Übergang (Promotion) | `POST /classes/{id}/promote` |
| Schulleitung-Dashboard | UI `/` (rollenbasiert) |
| Stellvertretungs-Übersicht | `GET/DELETE /substitutions` |
| Audit-Listing (Backend) | `GET /audit/events` |
| Self-Service-PW-Change Lehrer | `POST /teachers/{guid}/password-reset` |

---

## Voraussetzungen

- Zugriff auf den Docker-Host (SSH oder Portainer)
- Backup der PostgreSQL-Datenbank (siehe unten)
- `.env`-Datei mit den bestehenden Secrets

---

## 1. Datenbank-Backup

```bash
docker compose exec postgres pg_dump -U magister magister \
  | gzip > /backup/magister-before-m2-$(date +%Y%m%d-%H%M).sql.gz
```

---

## 2. Neues Image ziehen

```bash
docker compose pull
```

Erwartete neue Image-Tags:
- `ghcr.io/vita-brevis-gmbh/magister-api:0.2.x`
- `ghcr.io/vita-brevis-gmbh/magister-web:0.2.x`

---

## 3. Datenbank-Migrationen ausführen

M2 fügt **keine neuen Tabellen** hinzu — alle bestehenden Strukturen (insb. `class_teacher_roles.valid_to`, `ad_users.enabled`) waren bereits in M1 vorhanden. Alembic-Migrationen werden trotzdem zur Sicherheit ausgeführt:

```bash
docker compose run --rm api alembic upgrade head
```

Erwartete Ausgabe: `INFO  [alembic.runtime.migration] Running upgrade ... -> head`

---

## 4. Stack neustarten

```bash
docker compose up -d
```

---

## 5. Smoke-Tests

```bash
# Health-Check
curl -sf https://<deine-domain>/api/health | jq .

# Audit-Listing (erfordert Admin-Token)
curl -sf -H "Cookie: session=..." https://<deine-domain>/api/audit/events?limit=5 | jq .total

# Substitutions-Endpoint
curl -sf -H "Cookie: session=..." https://<deine-domain>/api/substitutions | jq length
```

---

## 6. Rollback (falls nötig)

```bash
# Altes Image-Tag eintragen in docker-compose.yml, dann:
docker compose up -d

# Keine DB-Migrationen rückgängig zu machen (M2 hat keine Schema-Änderungen)
```

---

## Bekannte Einschränkungen nach M2

- **Audit-Listing-Backend (PR #29):** Das `GET /audit/events`-Frontend ist auf diesem Branch; das Backend-PR muss separat gemergt und deployt werden, bevor die Audit-Tabelle in der UI erscheint.
- **FR/IT/EN Übersetzungen:** Die Locale-Dateien sind vollständig aber noch nicht durch native Reviewer geprüft — bitte vor dem ersten produktiven Einsatz mit Schulen in der jeweiligen Sprache reviewen.
