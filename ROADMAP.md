# Magister · ROADMAP

> **Magister** — User & class management for schools
> Part of **Schola Levis** by **Vita Brevis**

Roadmap-Sicht 2026. Konkrete Daten kommen pro Milestone in der README-Status-Sektion.

## M1 — Foundation (in Entwicklung)

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

## M2 — Lifecycle & Schulleitung-Power

**Ziel:** Schul-Operations-Aufgaben (Off-Boarding, Schuljahres-Übergänge) werden in Magister abgebildet, statt in der Schul-IT.

- AD User Enable/Disable durch Schulleitung (Off-Boarding bei Schulaustritt)
- Bulk-Class-Actions (mehrere Schüler in eine Klasse, Klassen-Move)
- Schuljahres-Übergangs-Helfer (Klasse 3a → 4a Promotion mit Bestätigungs-Dialog)
- Schulleitung-Dashboard: alle Klassen der Schule, KL-Übersicht, offene Resets
- Stellvertretungs-UI mit zeitlich begrenzten Berechtigungen
- Audit-Listing-UI (read-only Filter-Tabelle für Admin/Schulleitung)
- Self-Service-PW-Change für Lehrer (gegen AD)

## M3 — Process & Communication

**Ziel:** Magister wird zum Verbindungsstück zwischen IT, Schulleitung und Eltern.

- Eltern-Briefe-Templates (PDF-Generator) für Anmeldungen, Klassenwechsel, Reset-Hand-Out
- CSV-Import aus LehrerOffice / Sokrates / EvAlea (Stage → Diff → Apply)
- FR/IT/EN Übersetzungen produktiv
- Reporting-Endpoints (Schülerzahlen, KL-Auslastung, Audit-Reports)
- Datenexport für Betroffenenauskunft (CLI + UI)
- Compliance-Exports (revDSG-konformes Activity-Log pro User)

## M4 — Scale & Operations Maturity

**Ziel:** Vita Brevis kann viele Schulträger gleichzeitig betreiben, Schulträger können sich mehr selbst helfen.

- Multi-Schulträger pro Operations-Team (Vita Brevis Cockpit)
- Self-Service Update-Channels (`stable`, `latest`) mit Roll-Forward / Roll-Back
- ADR-getriebene Architektur-Doku, ausführliche Runbooks
- Performance-Optimierungen (Cache-Layer, AD-Diff-Sync)
- Härtungs-Audit + Penetration-Test

## Cross-Cutting (laufend)

- Sicherheits-Updates der Dependencies (renovate)
- Übersetzungsqualität FR/IT durch native Reviewer
- Operations-Dokumentation für Schulträger-IT (M2 Final-Pass)
