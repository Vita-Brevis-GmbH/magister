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

## M4 — Scale & Operations Maturity (abgeschlossen; externer Pentest terminiert)

**Ziel:** Vita Brevis kann viele Schulträger gleichzeitig betreiben, Schulträger können sich mehr selbst helfen.

**Akzeptanz:**
- ✅ **M4.1 Vita Brevis Cockpit Foundation** — Instanz-Inventar, Health-Polling, Version-Tracking (`cockpit/` Subtree, ADR-0003)
- ✅ **M4.2 Update-Tracking** — Release-Manifest-Poller, `update_requests`-Tabelle, "Update einplanen"-UI
- ✅ **M4.3 Update-Runner** — atomic claim/complete/fail-Endpoints, Python-Runner mit SSH + pg_dump-Snapshot + Smoke-Test, systemd-Service, Runbook `cockpit-update-runner.md`; `last_error`-Härtung (sanitisierter unexpected-Pfad + whitelist-taugliche Step-Tokens) + Runner-Tests
- ✅ **Performance: AD-Diff-Sync** — inkrementeller Sync via `whenChanged`-Cursor (ADR-0004)
- ✅ **Performance: Read-Cache** — in-process TTL-Cache mit version-stamped Invalidation, angewendet auf `ClassRepository.list_active`
- ✅ **Härtungs-Audit (Self-Assessment)** — `docs/security/hardening-audit-2026-06.md` mit 4 Medium-Findings als Pre-Pentest-Hardening-Liste
- ✅ **Erweiterte Runbooks** — `disaster-recovery.md`, `key-rotation.md`
- ⏳ Externer Pentest (Q4 2026 nach M5-Hardening)

## M5 — Pre-Pentest Hardening (Hardening abgeschlossen; Pentest terminiert)

**Ziel:** Alle Medium-Findings aus dem Hardening-Audit beheben, bevor externer Pentest gebucht wird.

**Akzeptanz:**
- ✅ M-01: Cockpit Service-Tokens (rotierbar, `expires_at`, `revoked`) — Tabelle `service_tokens`, CRUD unter `/api/service-tokens`
- ✅ M-02: `last_error`-Whitelist in Cockpit-Poller + Runner
- ✅ M-03: `audit_events.key_id`-Spalte (Migration 0011) für Multi-Key-Rotation
- ✅ M-04: CSV-Upload bounded auf 10 MiB (413 statt OOM)
- ✅ L-01 bis L-07 (Low-Findings) abgearbeitet — Code: L-03 (`sessionStorage`), L-04 (Postgres internal-only), L-06 (Cockpit-API-Security-Header); Doku/gegenstandslos: L-01 (HSTS bei Self-Signed bewusst aus), L-02 (`/api/healthz`-Angleich); L-07 bereits erledigt (Pagination vorhanden). Offen: L-05 (Ops-Infra)
- ✅ I-01 bis I-05 (Informational) abgearbeitet — ldap3-Renovate-Pin, `# type: ignore`-Begründungen, API-Healthcheck, CI-`permissions`, Session-URLs bereits sauber
- ⏳ Externer Pentest beauftragen (nach M5-Abschluss, Q4 2026)

## M6 — Modulare Funktionen & Company-Readiness (geplant)

**Ziel:** Magister über die Schule hinaus einsetzbar machen (Firmen /
Mischbetrieb) — **eine** Codebasis, **ein** Deployment-Stack. Fachliche
Funktionen werden zu einzeln schaltbaren Modulen über einer domänenneutralen
Basis; ein weiches Profil (Schule/Firma) setzt nur Vokabular und ein
empfohlenes Start-Set und sperrt nichts. Referenz:
[ADR-0008](docs/adr/0008-modulare-funktionen.md).

**Akzeptanz (phasenweise, je Phase einzeln lieferbar & rückwärtskompatibel):**

- ✅ **Phase 0 — Modul-Naht (kein Verhaltenswechsel):** `ModuleManifest` +
  Registry; `create_app()` mountet aktivierte Module statt 27× hartem
  `include_router`; bestehende Router in `platform` + `school` einsortiert;
  Frontend-Nav aus `GET /me/modules` statt hartkodiert in `Layout.tsx`. Prod
  läuft unverändert als reines Refactoring, CI grün.
- ✅ **Phase 1 — Schalter & Profil:** `instance_profile`
  (`school`/`company`/`neutral`) + `module_settings` in `app_settings`
  (versioniert, live über `effective_settings`); Admin-Seite „Module &
  Funktionen" mit Zwei-Ebenen-Schaltung (Profil-Preset + Einzel-Schieber je
  Modul), abhängigkeitsbewusst, „soft off" für Module mit Daten; Term-Packs
  (i18n-Overlay je Profil).
- ✅ **Phase 2 — Company-MVP:** `departments` + `manager_roles` +
  `memberships` + On-/Offboarding als eigene Modul-Tabellen (parallel zu
  `classes`, nicht generischer Diskriminator — ADR-0008 D6); Firmen-Term-Pack;
  nutzt PW-Reset/Lifecycle/Devices/Imports/Audit/Reports der Plattform.
- ⏳ **Phase 3 — Härten & optional splitten:**
  - ✅ **Request-Enforcement abgeschalteter Module:** Router werden statisch
    gemountet; jedes *toggelbare* Modul bekommt beim Mounten eine Guard-Dependency,
    die Requests an ein deaktiviertes Modul mit `404 module_disabled` abweist
    (effektive Menge aus Profil + Overrides). „Aus" heisst damit API-aus, nicht
    nur aus der Nav ausgeblendet; die nicht-toggelbare `platform`-Basis bleibt
    immer erreichbar.
  - ✅ **Modul-Vertrags-CI (Architektur-Fitness-Tests):** Registry-IDs == Katalog-IDs
    (jedes gemountete Modul hat Toggle-/Guard-Policy); jede eigene Route ist
    authentifiziert ausser auf einer expliziten, geprüften Public-Allowlist;
    jede toggelbare Modul-Route trägt den Guard, die `platform`-Basis nie;
    i18n-Locale-Parität (alle 4 Sprachen gleiche Keys) bereits durch
    `i18n.test.ts` erzwungen.
  - ✅ **RBAC von Rollennamen auf Capabilities:** Endpoints deklarieren die
    benötigte *Capability* (`auth/capabilities.py`), nicht die Rolle; eine
    zentrale `ROLE_CAPABILITIES`-Map verbindet Rollen mit Capabilities. Die
    `require_*`-Helfer bleiben als dünne `require_capability`-Wrapper erhalten
    (`require_role` nur noch für direkte Rollen-Gates); die Ad-hoc-Gates in
    users/audit/imports sind mitmigriert. Verhalten unverändert — eine
    Äquivalenz-Matrix pinnt jedes Gate auf exakt die frühere Rollen-Menge.
  - ✅ **Split-fähig — Modul → eigener Container (bei Bedarf):** Deployment-Achse
    getrennt von der Runtime-Achse. `MAGISTER_CONTAINER_MODULES` lässt dasselbe
    `magister-api`-Image als dedizierten Modul-Container laufen (nur die
    genannten Module + die immer aktive `platform`-Basis); unbekannte Ids werden
    beim Start abgewiesen. Overlay `deploy/compose/docker-compose.split.yml` +
    Runbook `docs/runbooks/promote-module-to-container.md` (leichter Env-Split
    **und** voller `git subtree split` wie `cockpit/`, ADR-0003), inkl.
    D5-Vorbehalt (geteilte DB/Secrets). Contract-Tests decken die
    Container-Auswahl ab.

**M6 — Benutzer-Zusatzfeatures (Product-Owner-Wunsch, ADR-0009):**

- ✅ **A — Mail-Aliase (proxyAddresses):** mehrere Adressen pro Benutzer
  (Standard + Zusatz); Schreiben ins on-prem-AD-Attribut `proxyAddresses`,
  Azure AD Connect legt sie in Exchange an. Neue `mail_aliases`-Cache-Spalte,
  Domain-Allowlist gilt, Sync-Readback. Grundlage für C.
- ✅ **B — Editierbare Vorlagen:** `document_templates` in der DB, im Admin-UI
  editierbar (Betreff/HTML + Platzhalter, Live-Vorschau im Sandbox-iframe, pro
  Sprache/Schule); Jinja2-**SandboxedEnvironment**-Renderer mit Fallback auf die
  eingebauten Templates (Brief-Override in `LetterService`). Kein SMTP.
- ✅ **C — Namensänderung-Assistent:** geführte Kaskade Nachname → Anzeigename
  → UPN → Mail → sAMAccountName in einem auditierten `user_renamed`-Vorgang;
  alte Adresse bleibt automatisch als Alias (nutzt A). Plus editierbare
  Org-/Kontakt-Attribute (Titel, Abteilung, Firma, Telefon, Mobil, Büro,
  Beschreibung, Personalnummer).

**Bewusst nicht in M6:**

- Rename `school_id` → `org_unit_id` (Kosmetik; Vokabular wechselt über
  Term-Packs, die Spalte/CI-Invariante bleibt).
- Ein Container pro Modul als Default (Schieber = Runtime-Komposition, nicht
  Deployment — ADR-0008 D5).

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
- ✅ **Schüler-Provisioning per CSV** — Import-Typ `students` legt neue AD-Accounts an (Migration 0015, ADR-0006), generierte lesbare Passwörter, Ziel-OU nach Zyklus, Zugangsdaten-PDFs (Handout + Klassentabelle)
- ✅ **Test/CI** — Coverage-Gate (75 %), Router-Tests, Rename-Integritätstests, Pre-commit spiegelt Frontend-CI

## Cross-Cutting (laufend)

- Sicherheits-Updates der Dependencies (renovate)
- Übersetzungsqualität FR/IT durch native Reviewer
- Operations-Dokumentation für Schulträger-IT
