# Magister · Documentation Index

Vollständige Dokumentation für **Magister** und das interne **Vita Brevis Cockpit**.

---

## Schnelleinstieg

| Du willst… | Lies… |
|---|---|
| Magister verstehen | [`README.md`](../README.md) → [`SPEC.md`](../SPEC.md) → [`ARCHITECTURE.md`](../ARCHITECTURE.md) |
| Magister auf einem Schulträger-Host installieren | [`scripts/install-magister.sh`](../scripts/install-magister.sh) (`--mode prod\|dev`, empfohlen) ODER [`runbooks/install-ubuntu.md`](runbooks/install-ubuntu.md) (manuell) |
| Das Cockpit (intern) installieren | [`runbooks/install-cockpit.md`](runbooks/install-cockpit.md) ODER [`scripts/install-cockpit.sh`](../scripts/install-cockpit.sh) |
| Eine bestehende Magister-Instanz upgraden | [`runbooks/upgrade-to-mX.md`](runbooks/) |
| Verstehen wie wir entscheiden | [`adr/`](adr/) |
| Roadmap sehen | [`../ROADMAP.md`](../ROADMAP.md) |

---

## Komponenten

### 1. Magister (`apps/api` + `apps/web`)

Das Schul-Tool. Eine Instanz pro Schulträger. Wird auf einem Linux-Host beim Schulträger (oder bei Vita Brevis im Auftrag) betrieben.

- Backend: FastAPI + SQLAlchemy + Postgres
- Frontend: React + Vite + TanStack Router
- Auth: OIDC (Entra ID) + on-prem AD (LDAPS)
- Deployment: Docker Compose hinter Caddy

**Doku:**
- Installation: [`runbooks/install-ubuntu.md`](runbooks/install-ubuntu.md) (manuell, sehr detailliert) — oder `scripts/install-magister.sh` (automatisch)
- Backend-Setup (Phasen): [`runbooks/setup.md`](runbooks/setup.md)
- Upgrades: [`runbooks/upgrade-to-m1.5.md`](runbooks/upgrade-to-m1.5.md), [`upgrade-to-m2.md`](runbooks/upgrade-to-m2.md), [`upgrade-to-m3.md`](runbooks/upgrade-to-m3.md)
- Demo-Daten: [`runbooks/demo.md`](runbooks/demo.md)

### 2. Cockpit (`cockpit/api` + `cockpit/web`)

Internes Ops-Tool von Vita Brevis. Verwaltet alle Magister-Instanzen zentral: Health-Polling, Versions-Tracking, Update-Scheduling.

- Backend: FastAPI + SQLAlchemy + Postgres
- Frontend: React + Vite + Tailwind
- Auth: Bootstrap-Token + rotierbare Service-Tokens
- Läuft hinter VPN/Tailscale, nicht öffentlich erreichbar

**Doku:**
- Installation: [`runbooks/install-cockpit.md`](runbooks/install-cockpit.md)
- Architektur: [`adr/0003-vita-brevis-cockpit.md`](adr/0003-vita-brevis-cockpit.md)
- Update-Runner: [`runbooks/cockpit-update-runner.md`](runbooks/cockpit-update-runner.md)

### 3. Cockpit Update-Runner (`cockpit/runner`)

Drainer für `pending` Update-Requests. Läuft als systemd-Service auf einem Ops-Host mit SSH-Zugriff auf alle Magister-Instanzen.

**Doku:** [`runbooks/cockpit-update-runner.md`](runbooks/cockpit-update-runner.md)

---

## Operations

| Runbook | Wann brauchst du das? |
|---|---|
| [`disaster-recovery.md`](runbooks/disaster-recovery.md) | Total-Loss eines Hosts oder DB-Korruption |
| [`key-rotation.md`](runbooks/key-rotation.md) | Audit-Key, OIDC-Secret oder AD-Bind-PW erneuern |
| [`cockpit-update-runner.md`](runbooks/cockpit-update-runner.md) | Update-Runner installieren oder warten |

---

## Sicherheit

- [`security/hardening-audit-2026-06.md`](security/hardening-audit-2026-06.md) — Self-Assessment + Pentest-Vorbereitung

---

## Architecture Decision Records

| ADR | Thema |
|---|---|
| [`0003`](adr/0003-vita-brevis-cockpit.md) | Cockpit als separates Ops-Tool |
| [`0004`](adr/0004-ad-incremental-sync.md) | AD-Diff-Sync via `whenChanged`-Cursor |

(ADRs 0001/0002 wurden vor M4 vergeben.)

---

## Setup-Scripts

| Script | Was tut es? |
|---|---|
| [`scripts/install-magister.sh`](../scripts/install-magister.sh) | Interaktiver End-to-End-Installer (Ubuntu/Debian): erzeugt Secrets + argon2-Hash, schreibt `.env`, startet den Stack. `--mode prod` (HTTPS/FQDN) oder `--mode dev` (HTTP/IP). Idempotent (bewahrt Secrets). |
| [`scripts/install-cockpit.sh`](../scripts/install-cockpit.sh) | Idempotenter Cockpit-Installer (Compose-Stack) |
| [`scripts/bootstrap-cockpit-token.sh`](../scripts/bootstrap-cockpit-token.sh) | Ersten Service-Token via Bootstrap-Token erzeugen |
| [`scripts/magister-cli`](../scripts/magister-cli) | Kleine Ops-CLI (z.B. Password-Hashing) |
