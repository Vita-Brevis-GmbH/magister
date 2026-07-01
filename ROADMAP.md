# Magister · ROADMAP

> **Magister** — User & class management for schools
> Part of **Schola Levis** by **Vita Brevis**

Roadmap-Sicht 2026. Konkrete Daten kommen pro Milestone in der README-Status-Sektion.

## M1 — Foundation (abgeschlossen)

**Ziel:** Magister liefert die Kern-Workflows für Klassenlehrer:innen + Schulleitung. Schulträger können produktiv mit Klassen arbeiten und Passwörter zurücksetzen.

**Akzeptanz (alle ✓):**
- AD-User-Listing und periodischer Sync funktional, Schul-Scope durchgesetzt
- Klassenlehrer-Klassifizierung mit n KL/Klasse + Sub-Rollen (haupt/co/stellvertretung)
- Schulklassen-CRUD inkl. Soft-Delete + Audit
- Klassen-Zuweisung Schüler/Lehrer mit `valid_from`/`valid_to`
- Schüler-PW-Reset (generate + manual mode), Forced-Change, vollständiges Audit
- OIDC-Login gegen Entra ID, Bootstrap-Admin via Env-Var
- RBAC: Admin / Schulleitung / Klassenlehrer
- Audit-Pipeline: jede Mutation ein Event in `audit_events`
- DE-UI vollständig; FR/IT/EN Locale-Files vorhanden (Übersetzungen vor M3-Produktiveinsatz)
- Docker-Compose-Stack reproduzierbar, Caddy-Auto-TLS
- E2E-Test gegen ldap3-MockServer und Test-Postgres

## M2 — Lifecycle & Schulleitung-Power (abgeschlossen)

**Ziel:** Schul-Operations-Aufgaben (Off-Boarding, Schuljahres-Übergänge) werden in Magister abgebildet, statt in der Schul-IT.

**Akzeptanz (alle ✓):**
- ✅ AD User Enable/Disable durch Schulleitung (Off-Boarding bei Schulaustritt)
- ✅ Bulk-Class-Actions (mehrere Schüler in eine Klasse, Klassen-Move) — `POST /classes/{id}/students/bulk` mit Savepoint-Partial-Success
- ✅ Schuljahres-Übergangs-Helfer (3a → 4a Promotion mit 3-Stufen-Bestätigungs-Dialog) — `POST /classes/{id}/promote`, optionales Archivieren der Quellklasse
- ✅ Schulleitung-Dashboard: Kennzahlkarten, Klassen-Übersicht, Off-Boarding-Queue (deaktivierte Accounts)
- ✅ Stellvertretungs-UI: cross-class Listenansicht mit Status-Tabs, Schnell-Widerruf — `GET/DELETE /substitutions`
- ✅ Audit-Listing-UI: gefilterte, dekryptierte Tabelle für Admin/Schulleitung — `GET /audit/events` (Backend PR #29)
- ✅ Self-Service-PW-Change für Lehrer (gegen AD)

**Ausstehend vor Produktiveinsatz:**
- PR #29 (Audit-Backend) muss gemergt werden
- FR/IT/EN Übersetzungen durch native Reviewer validieren
- Runbook `upgrade-to-m2.md` erstellen (Operations-Doku Schulträger-IT)

## M3 — Process & Communication (abgeschlossen)

**Ziel:** Magister wird zum Verbindungsstück zwischen IT, Schulleitung und Eltern.

**Akzeptanz:**
- ✅ Eltern-Briefe-Templates (PDF-Generator) für Anmeldungen, Klassenwechsel, Passwort-Übergabe — `POST /letters/{template}` mit WeasyPrint
- ✅ CSV-Import mit Stage → Diff → Apply für Klassen, Schüler-Zuteilungen, KL-Rollen — `POST /imports` + Template-Download
- ✅ Reporting-Endpoints: Schülerzahlen pro Klasse, KL-Auslastung, Audit-Activity — `GET /reports/*`
- ✅ Datenexport für Betroffenenauskunft (revDSG Art. 25) als JSON + CSV — `GET /privacy/subject-access/{guid}` mit self-audit
- ✅ Compliance-Activity-Log pro User (in Subject-Access-Endpoint integriert, `target` und `actor` getrennt)

**Ausstehend vor Produktiveinsatz:**
- FR/IT/EN-Übersetzungen durch native Reviewer (Stub-Status entfernen)
- Runbook `upgrade-to-m3.md` (siehe `docs/runbooks/`)

## M4 — Scale & Operations Maturity (in Arbeit)

**Ziel:** Vita Brevis kann viele Schulträger gleichzeitig betreiben, Schulträger können sich mehr selbst helfen.

**Akzeptanz:**
- ✅ **M4.1 Vita Brevis Cockpit Foundation** — Instanz-Inventar, Health-Polling, Version-Tracking (`cockpit/` Subtree, ADR-0003)
- ✅ **M4.2 Update-Tracking** — Release-Manifest-Poller, `update_requests`-Tabelle, "Update einplanen"-UI
- 🚧 **M4.3 Update-Runner** — atomic claim/complete/fail-Endpoints, Python-Runner mit SSH + pg_dump-Snapshot + Smoke-Test, systemd-Service, Runbook `cockpit-update-runner.md`
- ✅ **Performance: AD-Diff-Sync** — inkrementeller Sync via `whenChanged`-Cursor (ADR-0004)
- ✅ **Performance: Read-Cache** — in-process TTL-Cache mit version-stamped Invalidation, angewendet auf `ClassRepository.list_active`
- ✅ **Härtungs-Audit (Self-Assessment)** — `docs/security/hardening-audit-2026-06.md` mit 4 Medium-Findings als Pre-Pentest-Hardening-Liste
- ✅ **Erweiterte Runbooks** — `disaster-recovery.md`, `key-rotation.md`
- ⏳ Externer Pentest (Q4 2026 nach M5-Hardening)

## M5 — Pre-Pentest Hardening (in Arbeit)

**Ziel:** Alle Medium-Findings aus dem Hardening-Audit beheben, bevor externer Pentest gebucht wird.

**Akzeptanz:**
- ✅ M-01: Cockpit Service-Tokens (rotierbar, `expires_at`, `revoked`) — Tabelle `service_tokens`, CRUD unter `/api/service-tokens`
- ✅ M-02: `last_error`-Whitelist in Cockpit-Poller + Runner
- ✅ M-03: `audit_events.key_id`-Spalte (Migration 0011) für Multi-Key-Rotation
- ✅ M-04: CSV-Upload bounded auf 10 MiB (413 statt OOM)
- ⏳ L-01 bis L-07 (Low-Findings) als Backlog
- ⏳ Externer Pentest beauftragen

## Erweiterungen 2026-06 (post-Rollout, abgeschlossen)

**Ziel:** Verbesserungen und kleine Erweiterungen aus dem laufenden Betrieb, parallel zum Produktiv-Rollout. Referenz: [`docs/features/extensions-2026-06.md`](docs/features/extensions-2026-06.md).

**Akzeptanz (alle ✓):**
- ✅ **Schulen-Dropdown** bei Klassenerstellung — `GET /schools` (scope-aware)
- ✅ **Klassen-Detailfeld + Edit-Dialog** (Name/Kürzel/Details, Migration 0012); Schulwechsel bewusst ausgeschlossen
- ✅ **„Details anzeigen"** von der Klassenansicht in das User-Detail (Admin/SMI)
- ✅ **User-Dashboard** (`GET /users/{guid}/dashboard`: Klassen + KL) + **Edit-Modus** (read-only mit „Bearbeiten")
- ✅ **PW-Reset in der Klassenansicht** + Schüler-Klassenfilter (`?class_id` matcht Schüler)
- ✅ **AD-Verbindungstest** (`POST /admin/ad-test`, nur LDAP; Entra-PW-Test verworfen — MFA-Modell)
- ✅ **Einzelschüler-Übergang** — `student_guids`-Teilmenge im Promote
- ✅ **Per-User-Einstellungen** (Sprache/Region/Formate, Migration 0013, `/me/preferences`); Datums-/Zeit-/Zahlenformate werden über `lib/useFormatters` app-weit angewendet
- ✅ **Rolle Fachlehrer** — eigene Tabelle (Migration 0014, ADR-0005), Zuweisung mit Fach, PW-Reset für eigene Schüler:innen, „Meine Schüler"-Sicht
- ✅ **Test/CI** — Coverage-Gate (75 %), Router-Tests, Rename-Integritätstests, Pre-commit spiegelt Frontend-CI

## Cross-Cutting (laufend)

- Sicherheits-Updates der Dependencies (renovate)
- Übersetzungsqualität FR/IT durch native Reviewer
- Operations-Dokumentation für Schulträger-IT
