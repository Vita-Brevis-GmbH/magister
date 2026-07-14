# Upgrade-Runbook: v0.2.0 → v0.3.0

**Gilt für:** Magister-Instanzen auf `v0.2.0`
**Ziel-Version:** `v0.3.0`
**Aufwand:** ~10 Minuten Downtime (Image-Tausch + 3 additive Migrationen)

> Hinweis: Ältere Runbooks (`upgrade-to-m3.md`, `upgrade-to-extensions-2026-06.md`)
> nennen abweichende Migrations-Nummern aus einer früheren Nummerierung. Für dieses
> Upgrade gelten ausschliesslich die unten aufgeführten Revisionen (`0021`–`0023`).

---

## Was ist neu in v0.3.0

| Feature | Endpoints / Routes |
|---|---|
| LDAPS-Fix: Suchergebnisse unter SAFE_SYNC korrekt lesen, echte Fehler statt „leer" | AD-Sync / `POST /admin/ad-test` |
| Mehrjahrgangs-Klassen + Kindergarten (Stufenbereich) | `classes.jahrgangsstufe_bis`; UI Klassen anlegen/bearbeiten |
| Schulen-Verwaltung (Adresse, Kontakt, Beschreibung, Karte) | `GET/POST/PATCH/DELETE /schools` · UI `/admin/schools` |
| Ziel-Schule im Import-Wizard wählbar (Admins) | `POST /imports` mit `school_id` |
| Stufenbereich in der Klassen-CSV-Vorlage + Import | Import-Typ `classes` |
| Lehrpersonen-Import (neue AD-Konten) | Import-Typ `teachers` |
| Jahrgangsstufe pro Schüler:in (Import, User-Profil, Klassenaufstieg) | `ad_user_cache.jahrgangsstufe`; `POST /classes/{id}/promote` (`bump_grade`, `grade_overrides`) |
| Zugewiesene, aber noch nicht gestartete Schüler:innen erscheinen auf der Klassenliste | `GET /classes/{id}/students` |
| Globaler „Aktualisieren"-Button im Header | UI |
| UI aufgeräumt: „Meine Schüler:innen" nur für Lehrpersonen; Admin-Punkte unter „Einstellungen" | `GET /auth/me` liefert neu `kind` |
| AD-Flags „Passwort läuft nie ab" + „Benutzer kann Passwort nicht ändern" (pro User + CSV-Import) | `PATCH /users/{guid}`; Import-Typen `students`/`teachers` |
| Zugangsdaten-PDF pro User (Gerät + optionaler Custom-Text; Lehrer ohne Klassenliste) | `POST /users/{guid}/credential-pdf` |
| Mehrfach-Aktionen auf der User-Liste (aktivieren/deaktivieren/löschen/AD-Attribute) | UI (bestehende Einzel-Endpoints) |

---

## Voraussetzungen

- Zugriff auf den Docker-Host (SSH)
- Backup der PostgreSQL-Datenbank
- Bestehende `.env` — **keine neuen Env-Vars** in diesem Release
- **Nur für den Lehrpersonen-Import:** Der AD-Service-Account braucht Anlege-/
  Passwort-Setz-Rechte in der Lehrer-Ziel-OU (Admin → Einstellungen →
  Systemeinstellungen → Provisioning). Ohne Rechte/OU schlägt nur das Anlegen
  zeilenweise fehl (sichtbar im Import-Ergebnis) — alle übrigen Features laufen
  unabhängig davon.

---

## 1. Datenbank-Backup

```bash
cd /opt/magister/deploy/compose          # Pfad eurer Installation

sudo mkdir -p /backup
sudo chown "$(id -un)":"$(id -gn)" /backup

docker compose exec postgres pg_dump -U magister magister \
  | gzip > /backup/magister-before-v0.3.0-$(date +%Y%m%d-%H%M).sql.gz
ls -lh /backup/                           # Datei da und > 0 Byte?
```

---

## 2. Version pinnen (empfohlen)

In der `.env` die Image-Tags auf die neue Version setzen (reproduzierbar + sauberer Rollback):

```dotenv
MAGISTER_API_IMAGE=ghcr.io/vita-brevis-gmbh/magister-api:v0.3.0
MAGISTER_WEB_IMAGE=ghcr.io/vita-brevis-gmbh/magister-web:v0.3.0
```

> Ohne diese Zeilen läuft der Stack auf `:latest`; dann genügt `docker compose pull`.

---

## 3. Neue Images ziehen

```bash
docker compose pull magister-api magister-web
```

Erwartete Tags: `ghcr.io/vita-brevis-gmbh/magister-api:v0.3.0` und `…/magister-web:v0.3.0`.

### 3b. Alternative: Images auf dem Server bauen (ohne GHCR)

Wenn die GHCR-Images (noch) nicht gebaut sind:

```bash
cd /opt/magister
sudo git fetch origin
sudo git checkout main
sudo git pull --ff-only origin main

cd deploy/compose
docker compose -f docker-compose.yml -f docker-compose.build.yml build magister-api magister-web
```

---

## 4. Datenbank-Migrationen ausführen

Dieser Release bringt **vier additive Migrationen** (keine Umbauten bestehender Daten):

| Migration | Änderung |
|---|---|
| `0021_class_grade_range` | Spalte `classes.jahrgangsstufe_bis INT NULL` (Mehrjahrgang/Basisstufe) |
| `0022_school_details` | Spalten `schools.street/postal_code/city/phone/description/latitude/longitude` + `schools.updated_at` |
| `0023_student_jahrgangsstufe` | Spalte `ad_user_cache.jahrgangsstufe INT NULL`; erweitert den `import_jobs.kind`-Check um `teachers` |
| `0024_ad_pw_flags` | Spalten `ad_user_cache.password_never_expires` + `cannot_change_password` (BOOL, default false) |
| `0025_password_vault` | `ad_user_cache.store_password` (BOOL) + `password_enc` (BYTEA), `app_settings.password_store_enabled` (BOOL) |

Der Container-Entrypoint führt `alembic upgrade head` beim Start automatisch aus.
Für einen kontrollierten Lauf vor dem Neustart:

```bash
docker compose run --rm magister-api alembic upgrade head
```

Erwartete Ausgabe:

```
Running upgrade 0020_devices          -> 0021_class_grade_range
Running upgrade 0021_class_grade_range -> 0022_school_details
Running upgrade 0022_school_details    -> 0023_student_jahrgangsstufe
Running upgrade 0023_student_jahrgangsstufe -> 0024_ad_pw_flags
Running upgrade 0024_ad_pw_flags        -> 0025_password_vault
```

> **Passwort-Tresor:** Die optionale Passwort-Speicherung (pro User + globaler
> Schalter unter Einstellungen) verschlüsselt mit `MAGISTER_AUDIT_KEY` (bzw.
> `MAGISTER_SECRETS_KEY`) — server-seitig, nicht in der DB. Ohne gesetzten
> Schlüssel bleibt das Feature ungenutzt; keine neue Env-Var nötig.

> **AD-Validierung:** „Benutzer kann Passwort nicht ändern" wird im AD über den
> Security-Descriptor (DACL) gesetzt und konnte nicht gegen echtes AD getestet
> werden. Vor dem produktiven Einsatz an einem Testkonto prüfen. „Passwort läuft
> nie ab" (UAC-Bit) ist unkritisch.

> **Service-Name:** In der aktuellen `docker-compose.yml` heisst der API-Service `magister-api`.

---

## 5. Stack neustarten

```bash
docker compose up -d
```

Nur `magister-api` und `magister-web` werden ersetzt.

---

## 6. Smoke-Tests

```bash
# Health
curl -sf https://<deine-domain>/api/healthz && echo OK

# /auth/me liefert neu das Feld "kind" (Admin/Lehrer-Session)
curl -sf -H "Cookie: magister_session=..." https://<deine-domain>/api/auth/me | jq '{upn, is_admin, kind}'

# Schulen-Liste
curl -sf -H "Cookie: magister_session=..." https://<deine-domain>/api/schools | jq '.[0]'
```

Frontend-Smoke (Browser):
- **Als Lehrperson** einloggen → Nav zeigt **„Meine Schüler:innen"**; kein „Einstellungen"-Menü.
- **Als Admin/Schulleitung/SMI** → oben rechts **„Einstellungen ▾"** mit
  Benutzerverwaltung, Schulen, Audit-Log, Rollen, Stellvertretungen,
  Systemeinstellungen. **„Stellvertretungen"** ist nicht mehr in der obersten Leiste.
- **Schulen** (`/admin/schools`): Schule anlegen/bearbeiten inkl. Adresse + Karte.
- **Klasse** anlegen: Stufenbereich (von/bis, Kindergarten −1/0) wählbar.
- **Import** → Typ „Lehrpersonen" vorhanden; Klassen-Vorlage enthält `jahrgangsstufe_bis`.

---

## 7. Rollback (falls nötig)

```bash
# alten Tag in .env (v0.2.0) eintragen, dann:
docker compose up -d

# Migrationen zurückrollen — nur wenn die neuen Daten verworfen werden dürfen:
docker compose run --rm magister-api alembic downgrade 0020_devices
```

⚠ Der Downgrade verwirft `classes.jahrgangsstufe_bis`, alle Schul-Detailspalten
und `ad_user_cache.jahrgangsstufe` inklusive Daten und setzt den
`import_jobs.kind`-Check auf den alten Stand (ohne `teachers`) zurück. Im Zweifel
das Backup aus Schritt 1 einspielen.

---

## Nach dem Upgrade

- **Lehrpersonen** erhalten das aufgeräumte Menü; „Meine Schüler:innen" ist ihre
  Einstiegsseite.
- **Admins** finden alle Verwaltungsfunktionen gebündelt unter „Einstellungen".
- **Jahrgangsstufen** können pro Schüler:in gepflegt und beim Klassenaufstieg
  angepasst werden (Standard +1, Ausnahmen möglich).
