# Hardening-Audit · 2026-06

**Scope:** Magister M4 (Tag `v0.4.x`) inkl. Cockpit
**Methodik:** Self-Assessment durch Vita-Brevis-Engineering vor externem Pentest
**Reviewer:** Engineering-Lead + Sicherheitsverantwortlicher

---

## Zusammenfassung

Magister ist aus Architektursicht solide: defense-in-depth durch LDAPS-Sealed/Signed-Bind, `pgcrypto`-encrypted Audit-Payloads, RBAC an jedem Endpoint, Schul-Scope-Filter zentral im Repository-Layer. Es gibt **keinen Critical-Befund**. Alle 4 Medium-Befunde wurden im M5-Pre-Pentest-Hardening-Block behoben.

| Severity | Anzahl |
|---|---|
| Critical | 0 |
| High | 0 |
| Medium | 4 |
| Low | 7 |
| Informational | 5 |

---

## Threat-Model (vereinfacht)

| Akteur | Capability | Magister-Mitigation |
|---|---|---|
| Externer Angreifer | HTTP-Requests, keine Credentials | Caddy TLS 1.3, OIDC erzwungen, Rate-Limit pro IP |
| Phishing-Opfer (Lehrer) | Gestohlene OIDC-Session | Conditional Access (MFA), Session-Max-Idle 30min, Audit jeder Mutation |
| Schulleitung (legitim) | Vollzugriff auf Schul-Scope | RBAC; Audit |
| Insider Vita Brevis Ops | Container-Zugriff | Audit, Key-Rotation, kein direkter DB-Schreibzugriff |
| Kompromittierter AD-DC | Beliebige LDAP-Antworten | objectGUID immutability check; signed bind; sanity validation an Pydantic |

---

## Findings

### M-01 · Bootstrap-Token im Cockpit als statischer Wert ✅ behoben

**Severity:** Medium
**File:** `cockpit/api/cockpit_api/auth.py`, `cockpit/api/cockpit_api/models/service_token.py`
**Status:** Behoben in M5 — `service_tokens`-Tabelle mit `token_hash` (sha256), `expires_at`, `revoked`. CRUD-Endpoints unter `/api/service-tokens` (Bootstrap-Token bleibt als Break-Glass-Credential).
**Migration:** `0003_service_tokens`.

### M-02 · `last_error`-Feld im Cockpit kann sensitive Daten leaken ✅ behoben

**Severity:** Medium
**File:** `cockpit/api/cockpit_api/services/health_poller.py`, `cockpit/runner/cockpit_runner/executor.py`
**Status:** Behoben in M5 — Whitelist (`http_<code>`, `unreachable`, `timeout`, `connect_error`, `transport_error`, `smoke_test_*`, `<step>_failed`). Stdout/stderr von Remote-Calls landet ausschliesslich im journald-Log des Runners, nicht in der Cockpit-DB.

### M-03 · `MAGISTER_AUDIT_KEY` ohne Versionierung ✅ behoben

**Severity:** Medium
**File:** `apps/api/magister_api/audit/service.py`, `apps/api/magister_api/models/audit.py`
**Status:** Behoben in M5 — Spalte `audit_events.key_id` (Migration 0011, default `v1`). Setting `MAGISTER_AUDIT_KEY_ID` (default `v1`) wird beim Insert mitgeschrieben. Multi-Key-Decryption in `audit/service.read()` folgt im Rotation-Tooling.

### M-04 · CSV-Import ohne Größenlimit ✅ behoben

**Severity:** Medium
**File:** `apps/api/magister_api/routers/imports.py`
**Status:** Behoben in M5 — `Content-Length`-Pre-Check + bounded `file.read(max_bytes + 1)` mit 10 MiB-Limit. Response: 413 Payload Too Large.

### L-01 bis L-07 · Low-Findings (Excerpt)

- L-01: HSTS-Max-Age in Caddy auf 6 Monate gesetzt — Empfehlung 1 Jahr nach Production-Stabilität
- L-02: `/api/version`-Endpoint existiert nicht (Cockpit fragt `/api/healthz` ab, was Version mitliefert) — Inkonsistenz mit Runbook
- L-03: Frontend `localStorage.cockpit_token` — sollte auf `sessionStorage` umgestellt werden (kein Persist über Tab-Close)
- L-04: Docker-Compose-Network exposed `postgres:5432` zum Host — sollte rein internal sein
- L-05: Backup-Dateien werden nicht in einem read-only-Bucket abgelegt
- L-06: Keine `Content-Security-Policy` strict für Frontend gesetzt
- L-07: Audit-Listing-UI hat keine Pagination — bei >10k Events DoS-Vektor

### I-01 bis I-05 · Informational

- I-01: ldap3-Version pinning fehlt — Renovate aktivieren
- I-02: pyright strict mode an, aber ein paar `# type: ignore` ohne Reason-Comment
- I-03: docker-compose-Healthcheck für API fehlt
- I-04: GitHub Actions ohne `permissions: contents: read` Default
- I-05: Docs verweisen auf `claude.ai/code/session_*` URLs — vor public Release entfernen

---

## Vorbereitung für externen Pentest

1. **M-01 bis M-04 fixen** (geplant für M5, Pre-Pentest-Block)
2. **Pentest-Scope-Dokument** erstellen mit:
   - Out-of-scope: Entra ID, AD-DC der Schulträger (sind Eigentum der Kunden)
   - In-scope: Magister-API, Web, Cockpit, Update-Runner
   - Erlaubt: authenticated + unauthenticated; Black-Box + Grey-Box (Code-Zugang nach Black-Box-Phase)
3. **Pentester wählen**: 2 Offerten einholen — bisherige Erfahrung mit Schweizer Schul-IT bevorzugt
4. **Budget**: ~CHF 25k für 5 Tester-Tage + Report
5. **Termin**: nach Abschluss M5 (geplant Q4 2026)

---

## Nächste Schritte

- [ ] Issues M-01..M-04 in GitHub als Milestone "pre-pentest-hardening" anlegen
- [ ] L-01..L-07 als Tickets im Backlog
- [ ] I-01..I-05 in Cross-Cutting-Aufgaben verteilen
- [ ] Quartalsweise Self-Re-Audit, Diff-Doku als `hardening-audit-<YYYY-QN>.md`
