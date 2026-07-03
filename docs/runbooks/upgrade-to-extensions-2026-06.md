# Upgrade-Runbook: M3 → Erweiterungen 2026-06 (v0.4.0)

**Gilt für:** Magister-Instanzen auf M3-Stand (`v0.3.x`)
**Ziel-Version:** Erweiterungen 2026-06 (`v0.4.0`)
**Aufwand:** ~10 Minuten Downtime (nur Image-Tausch + 4 additive Migrationen)

Referenz für den Funktionsumfang: [`docs/features/extensions-2026-06.md`](../features/extensions-2026-06.md).

---

## Was ist neu

| Feature | Endpoints / Routes |
|---|---|
| Schulen-Dropdown bei Klassenerstellung | `GET /schools` · UI Klassenerstellung |
| Klassen-Detailfeld + Edit-Dialog | `PATCH /classes/{id}` (`name`/`kuerzel`/`details`) |
| „Details anzeigen" Klasse → User | UI-Link `/users/$guid` (Admin/SMI) |
| User-Dashboard + Edit-Modus | `GET /users/{guid}/dashboard` |
| PW-Reset in Klassenansicht + Schüler-Klassenfilter | `GET /users?class_id=…` matcht nun auch Schüler |
| AD-Verbindungstest (nur LDAP) | `POST /admin/ad-test` |
| Einzelschüler-Übergang | `POST /classes/{id}/promote` mit `student_guids` |
| Per-User-Einstellungen (Sprache/Region/Formate) | `GET/PUT /me/preferences` |
| Rolle Fachlehrer + „Meine Schüler" | `GET/POST/DELETE /classes/{id}/subject-teachers`, `GET /me/students` |
| Schüler-Provisioning per CSV (neue AD-Accounts) | Import-Typ `students`, `POST /imports/handouts` (PDFs) · ADR-0006 |

---

## Voraussetzungen

- Zugriff auf den Docker-Host (SSH)
- Backup der PostgreSQL-Datenbank
- Bestehende `.env` — **keine neuen Env-Vars** in diesem Batch
- **Nur für das Schüler-Provisioning:** Der AD-Service-Account (Bind-User)
  braucht **Anlege- + Passwort-Setz-Rechte** in den Ziel-OUs. Die drei Ziel-OUs
  (Schüler Zyklus 3 · übrige · Lehrer) werden nach dem Upgrade unter
  **Admin → Einstellungen** gesetzt. Ohne diese Rechte/OUs schlägt das Anlegen
  zeilenweise fehl (sichtbar im Import-Ergebnis, kein Totalabbruch) — die
  übrigen Features funktionieren unabhängig davon.

---

## 1. Datenbank-Backup

```bash
cd /opt/magister/deploy/compose          # Pfad eurer Installation

docker compose exec postgres pg_dump -U magister magister \
  | gzip > /backup/magister-before-v0.4.0-$(date +%Y%m%d-%H%M).sql.gz
```

---

## 2. Version pinnen (empfohlen)

In der `.env` die Image-Tags auf die neue Version setzen (reproduzierbar + sauberer Rollback):

```dotenv
MAGISTER_API_IMAGE=ghcr.io/vita-brevis-gmbh/magister-api:v0.4.0
MAGISTER_WEB_IMAGE=ghcr.io/vita-brevis-gmbh/magister-web:v0.4.0
```

> Ohne diese Zeilen läuft der Stack auf `:latest`; dann genügt `docker compose pull`.

---

## 3. Neue Images ziehen

```bash
docker compose pull magister-api magister-web
```

Erwartete Tags: `ghcr.io/vita-brevis-gmbh/magister-api:v0.4.0` und `…/magister-web:v0.4.0`.

---

## 3b. Alternative: Images auf dem Server bauen (ohne GHCR)

Wenn die GHCR-Images (noch) nicht gebaut sind — z.B. um den aktuellen `main`
zu fahren, bevor ein Release-Tag Images erzeugt hat — baust du sie direkt aus
dem Quellcode-Checkout (`/opt/magister`) mit dem Build-Override
`docker-compose.build.yml`:

```bash
cd /opt/magister
sudo git fetch origin
sudo git checkout main
sudo git pull --ff-only origin main        # jetzt auf dem Stand mit allen neuen Funktionen

cd deploy/compose
docker compose -f docker-compose.yml -f docker-compose.build.yml build magister-api magister-web
```

Die Images werden mit genau den Namen getaggt, die die Basis-Compose erwartet
(`MAGISTER_API_IMAGE` / `MAGISTER_WEB_IMAGE`, Default `…:latest`), sodass die
folgenden Schritte (Migration + `up -d`) unverändert funktionieren.

> **Plain-HTTP-/Dev-Host** (ohne DNS/Zertifikat, erreichbar per IP): den
> Dev-Override dazunehmen und in einem Rutsch bauen + starten:
> ```bash
> docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.build.yml up -d --build
> ```
> Danach direkt weiter zu Schritt 4 (Migrationen).

---

## 4. Datenbank-Migrationen ausführen

Dieser Batch bringt **vier additive Migrationen** (keine Umbauten bestehender Tabellen):

| Migration | Änderung |
|---|---|
| `0012_class_details` | Spalte `classes.details TEXT NULL` |
| `0013_user_preferences` | Tabelle `user_preferences` (PK `ad_object_guid`) |
| `0014_subject_teacher_roles` | Tabelle `subject_teacher_roles` |
| `0015_provisioning_ous` | 3 Ziel-OU-Spalten in `app_settings`; erweitert den `import_jobs.kind`-Check um `students` |

```bash
docker compose run --rm magister-api alembic upgrade head
```

Erwartete Ausgabe:

```
Running upgrade 0011_audit_key_id      -> 0012_class_details
Running upgrade 0012_class_details     -> 0013_user_preferences
Running upgrade 0013_user_preferences  -> 0014_subject_teacher_roles
Running upgrade 0014_subject_teacher_roles -> 0015_provisioning_ous
```

> **Service-Name:** In der aktuellen `docker-compose.yml` heisst der API-Service
> `magister-api` (ältere Runbooks nutzen noch `api`).

---

## 5. Stack neustarten

```bash
docker compose up -d
```

Nur die geänderten Container (`magister-api`, `magister-web`) werden ersetzt.

---

## 6. Smoke-Tests

```bash
# Health
curl -sf https://<deine-domain>/api/health | jq .

# Schulen-Dropdown (Admin/Schulleitung-Session)
curl -sf -H "Cookie: session=..." https://<deine-domain>/api/schools | jq '.[0]'

# Eigene Einstellungen
curl -sf -H "Cookie: session=..." https://<deine-domain>/api/me/preferences | jq .

# AD-Verbindungstest (Admin)
curl -sf -X POST -H "Cookie: session=..." https://<deine-domain>/api/admin/ad-test | jq .
```

Frontend-Smoke (Browser):
- Login als Schulleitung → Klasse anlegen: **Schule als Dropdown** statt ID.
- Klassen-Detail → **„Bearbeiten"** (Name/Kürzel/Details), **„Fachlehrpersonen"**-Sektion,
  **PW-Reset** in der Schülertabelle.
- Nav **„Meine Schüler"** lädt.
- `/me` → **Einstellungs-Card**: Sprache/Region/Format speichern; Datumsformat greift
  app-weit (Audit-Log, Importe, User-Liste).

---

## 7. Rollback (falls nötig)

```bash
# alte Tags in .env (z.B. v0.3.x) eintragen, dann:
docker compose up -d

# Migrationen zurückrollen — nur wenn die neuen Daten verworfen werden dürfen:
docker compose run --rm magister-api alembic downgrade 0011_audit_key_id
```

⚠ Der Downgrade verwirft `subject_teacher_roles`, `user_preferences`, die
`app_settings`-OU-Spalten und die Spalte `classes.details` inklusive Daten.
Bereits provisionierte AD-Accounts bleiben in AD bestehen (Sync holt sie
wieder in den Cache). Im Zweifel das Backup aus Schritt 1 einspielen.

---

## Nach dem Upgrade

- **Schulleitung** über den Fachlehrer-Workflow und „Meine Schüler" onboarden.
- **Fachlehrpersonen** dürfen die Passwörter *ihrer* Schüler:innen zurücksetzen
  (aktive Zuweisung vorausgesetzt).
- **Per-User-Formate**: Datums-/Zeit-/Zahlenformat pro User unter `/me`.
