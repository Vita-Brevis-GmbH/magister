# Hardening-Audit · 2026-06

**Scope:** Magister M4 (Tag `v0.4.x`) inkl. Cockpit
**Methodik:** Self-Assessment durch Vita-Brevis-Engineering vor externem Pentest
**Reviewer:** Engineering-Lead + Sicherheitsverantwortlicher

---

## Zusammenfassung

Magister ist aus Architektursicht solide: defense-in-depth durch LDAPS-Sealed/Signed-Bind, `pgcrypto`-encrypted Audit-Payloads, RBAC an jedem Endpoint, Schul-Scope-Filter zentral im Repository-Layer. Es gibt **keinen Critical-Befund**. Alle 4 Medium-Befunde wurden im M5-Pre-Pentest-Hardening-Block behoben. Die 7 Low- und 5 Informational-Befunde sind im M5-Abschluss (2026-08) abgearbeitet — offen bleiben einzig **L-05** (Ops-Infra, read-only Backup-Bucket) und der **externe Pentest**.

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

### L-01 bis L-07 · Low-Findings

Disposition im M5-Abschluss (2026-08):

- L-01 ✅ **gegenstandslos** — HSTS ist im ausgelieferten Offline-Default (self-signed *internal*-Cert) bewusst deaktiviert; der Header würde den einmaligen „Zertifikat-Ausnahme akzeptieren"-Bypass sperren (Kommentar in `deploy/caddy/Caddyfile`). Bei importiertem, öffentlich vertrautem Zertifikat wäre der Wert 1 Jahr. `ARCHITECTURE.md` §5.1 entsprechend präzisiert.
- L-02 ✅ **behoben** — die Docs (ADR-0003, `cockpit/README.md`) nannten `/api/health` + `/api/version`; der reale, vom Health-Poller genutzte Magister-Endpoint ist `/api/healthz` (liefert Status + Version). Docs angeglichen.
- L-03 ✅ **behoben** — Cockpit-Token von `localStorage` auf `sessionStorage` umgestellt (`cockpit/web/src/App.tsx`, `api.ts`).
- L-04 ✅ **behoben** — Postgres-Host-Port (`5433:5432`) aus `cockpit/deploy/docker-compose.yml` entfernt; die DB ist nur noch über das Compose-Netz erreichbar. (Der Magister-Compose war bereits internal-only.)
- L-05 ⏳ **Ops** — read-only Backup-Bucket ist eine Deployment-/Infra-Massnahme des Betreibers, kein App-Code. Bleibt bei Vita-Brevis-Ops.
- L-06 ✅ **behoben (API)** — die Cockpit-API setzt jetzt Baseline-Security-Header inkl. CSP (`default-src 'none'; frame-ancestors 'none'`) per Middleware. Die Dokument-CSP der Cockpit-SPA folgt mit dem Prod-Reverse-Proxy (spiegelt `deploy/caddy/Caddyfile`), sobald das Cockpit produktiv ausgeliefert wird — heute läuft die SPA Vite-only hinter VPN.
- L-07 ✅ **bereits erledigt** — das Audit-Listing paginiert bereits: Backend `GET /audit/events` cappt `limit ≤ 200` und liefert `total`, die UI (`_app.admin.audit.tsx`) hat prev/next mit Seiten-Offset. Kein unbounded Fetch.

### I-01 bis I-05 · Informational

Disposition im M5-Abschluss (2026-08):

- I-01 ✅ **behoben** — Renovate-Regel für `ldap3` ergänzt (eigener, gelabelter PR, `rangeStrategy: pin`), analog zum Linter-Pin. ldap3 treibt den AD-Write-Pfad (unicodePwd/Bind-Encoding) und wird nicht mehr stillschweigend mitgezogen.
- I-02 ✅ **behoben** — alle sieben `# type: ignore` in `apps/api` mit Begründungs-Kommentar versehen.
- I-03 ✅ **behoben** — Healthcheck für `magister-api` im Compose ergänzt (stdlib-Probe gegen `/healthz`).
- I-04 ✅ **behoben** — `permissions: contents: read` als Default-Token in `backend-ci.yml` + `frontend-ci.yml` (release.yml hatte es bereits).
- I-05 ✅ **bereits sauber** — kein `claude.ai/code/session_*`-Verweis mehr in Docs oder Code (repo-weit verifiziert).

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
- [x] L-01..L-07 im M5-Abschluss abgearbeitet (L-05 bleibt Ops; Disposition oben)
- [x] I-01..I-05 im M5-Abschluss abgearbeitet (Disposition oben)
- [ ] Quartalsweise Self-Re-Audit, Diff-Doku als `hardening-audit-<YYYY-QN>.md`
