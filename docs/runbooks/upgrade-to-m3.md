# Upgrade-Runbook: M2 → M3

**Gilt für:** Magister-Instanzen auf M2-Stand (Tag `v0.2.x`)
**Ziel-Version:** M3 (`v0.3.x`)
**Aufwand:** ~20 Minuten Downtime (System-Libs für WeasyPrint)

---

## Was ist neu in M3

| Feature | Endpoints / Routes |
|---|---|
| CSV-Import mit Stage→Diff→Apply | `GET /imports/templates/{kind}.csv`, `POST /imports`, `GET /imports/{id}`, `POST /imports/{id}/apply`, `DELETE /imports/{id}`, `GET /imports` · UI `/admin/imports` |
| Eltern-Briefe als PDF | `POST /letters/{template}` (`enrollment` / `class_change` / `password_handout`) · UI: „Brief"-Button pro Schüler in der Klassen-Detailseite |
| Reporting | `GET /reports/students-by-class`, `/reports/teacher-workload`, `/reports/activity` · UI `/admin/reports` |
| Subject-Access / revDSG Art. 25 | `GET /privacy/subject-access/{guid}`, `/privacy/subject-access/{guid}/export.csv` · UI: „Datenauskunft"-Sektion auf User-Detail |

---

## Voraussetzungen

- Zugriff auf den Docker-Host (SSH oder Portainer)
- Backup der PostgreSQL-Datenbank
- `.env`-Datei mit den bestehenden Secrets (keine neuen Env-Vars in M3)

---

## 1. Datenbank-Backup

```bash
docker compose exec postgres pg_dump -U magister magister \
  | gzip > /backup/magister-before-m3-$(date +%Y%m%d-%H%M).sql.gz
```

---

## 2. Neues Image ziehen

```bash
docker compose pull
```

Erwartete neue Image-Tags:
- `ghcr.io/vita-brevis-gmbh/magister-api:0.3.x`
- `ghcr.io/vita-brevis-gmbh/magister-web:0.3.x`

**Im API-Image neu:** WeasyPrint-System-Libraries (Pango / Cairo / GDK-PixBuf / HarfBuzz). Werden im Dockerfile installiert — keine Konfig auf dem Host nötig.

---

## 3. Datenbank-Migrationen ausführen

M3 fügt **eine neue Migration** (`0009_import_jobs`) hinzu: zwei Tabellen `import_jobs` und `import_staged_rows` (kein Refactor bestehender Tabellen).

```bash
docker compose run --rm api alembic upgrade head
```

Erwartete Ausgabe: `INFO  [alembic.runtime.migration] Running upgrade 0008_computers_search_base -> 0009_import_jobs`

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

# Templates-Download (Admin-Token)
curl -sf -H "Cookie: session=..." https://<deine-domain>/api/imports/templates/classes.csv | head -2

# Reports
curl -sf -H "Cookie: session=..." https://<deine-domain>/api/reports/students-by-class | jq .total_students

# Subject-Access (mit echtem GUID)
curl -sf -H "Cookie: session=..." https://<deine-domain>/api/privacy/subject-access/<guid> | jq .user.upn
```

Frontend-Smoke:
- Browser → Login als Schulleitung
- Nav: „Importe" sichtbar, Template-Download produziert CSV
- User-Detail-Seite → „Datenauskunft anzeigen" → Modal lädt
- Klassen-Detail → „Brief"-Button pro Schüler → PDF-Download funktioniert

---

## 6. Rollback (falls nötig)

```bash
# Altes Image-Tag in docker-compose.yml eintragen, dann:
docker compose up -d

# Migration zurückrollen — nur falls M3-Daten nicht behalten werden müssen:
docker compose run --rm api alembic downgrade 0008_computers_search_base
```

⚠ Der Downgrade löscht die Tabellen `import_jobs` und `import_staged_rows` inklusive aller bisher stagedten Imports. Wenn produktive Imports gerade laufen, vorher abwarten oder verwerfen.

---

## Bekannte Einschränkungen nach M3

- **FR/IT/EN-Übersetzungen** sind als Stubs vollständig vorhanden, aber nicht durch native Reviewer geprüft (`_meta._status` in den Locale-Dateien). Vor dem Rollout an FR/IT-Schulen unbedingt reviewen lassen.
- **Eltern-Briefe sind aktuell nur in Deutsch** verfügbar. Texte in `magister_api/letters/translations.py`.
- **Audit-Decryption im Subject-Access** liest mit dem aktiven `MAGISTER_AUDIT_KEY` — bei Key-Rotation müssten alte Events vorher re-encryptet werden (Out-of-scope für M3).

---

## Nach dem Upgrade

- **Schul-IT informieren** über CSV-Import-Workflow (entlastet sie zum Schuljahreswechsel)
- **Schulleitung onboarden** auf neue PDF-Briefe und Subject-Access-Funktion (revDSG-Pflicht)
- **Reports** sind read-only und ohne Konfigurationsaufwand sofort verfügbar
