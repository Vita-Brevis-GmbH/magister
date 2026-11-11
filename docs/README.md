# Magister · Documentation Index

Vollständige Dokumentation für **Magister**. Das interne **Vita Brevis Cockpit** liegt seit 2026-11-11
im eigenen Repo [`Vita-Brevis-GmbH/vitabrevis-cockpit`](https://github.com/Vita-Brevis-GmbH/vitabrevis-cockpit) (privat).

---

## Schnelleinstieg

| Du willst… | Lies… |
|---|---|
| Magister verstehen | [`README.md`](../README.md) → [`SPEC.md`](../SPEC.md) → [`ARCHITECTURE.md`](../ARCHITECTURE.md) |
| Magister auf einem Schulträger-Host installieren | [`scripts/install-magister.sh`](../scripts/install-magister.sh) (`--mode prod\|dev`, empfohlen) ODER [`runbooks/install-ubuntu.md`](runbooks/install-ubuntu.md) (manuell) |
| Das Cockpit (intern) installieren | Repo `Vita-Brevis-GmbH/vitabrevis-cockpit`, `docs/runbooks/install-cockpit.md` |
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
- Upgrades: [`runbooks/upgrade-to-m1.5.md`](runbooks/upgrade-to-m1.5.md), [`upgrade-to-m2.md`](runbooks/upgrade-to-m2.md), [`upgrade-to-m3.md`](runbooks/upgrade-to-m3.md), [`upgrade-to-extensions-2026-06.md`](runbooks/upgrade-to-extensions-2026-06.md)
- Demo-Daten: [`runbooks/demo.md`](runbooks/demo.md)

### 2. Cockpit (ausgelagert)

Das interne Ops-Tool von Vita Brevis ist seit 2026-11-11 ein eigenes Repo:
[`Vita-Brevis-GmbH/vitabrevis-cockpit`](https://github.com/Vita-Brevis-GmbH/vitabrevis-cockpit)
(Verlauf von `cockpit/` erhalten). Dort liegen Installation, Update-Runner, Runbooks und Skripte.
Das Cockpit verwaltet künftig alle Produkte (Magister, Automato, NetBox, Keycloak); Magister bleibt
das erste Produkt. Hintergrund: [`adr/0003-vita-brevis-cockpit.md`](adr/0003-vita-brevis-cockpit.md) (Nachtrag).

---

## Operations

| Runbook | Wann brauchst du das? |
|---|---|
| [`disaster-recovery.md`](runbooks/disaster-recovery.md) | Total-Loss eines Hosts oder DB-Korruption |
| [`key-rotation.md`](runbooks/key-rotation.md) | Audit-Key, OIDC-Secret oder AD-Bind-PW erneuern |

---

## Sicherheit

- [`security/hardening-audit-2026-06.md`](security/hardening-audit-2026-06.md) — Self-Assessment + Pentest-Vorbereitung

---

## Architecture Decision Records

| ADR | Thema |
|---|---|
| [`0003`](adr/0003-vita-brevis-cockpit.md) | Cockpit als separates Ops-Tool (seit 2026-11-11 eigenes Repo) |
| [`0004`](adr/0004-ad-incremental-sync.md) | AD-Diff-Sync via `whenChanged`-Cursor |
| [`0005`](adr/0005-fachlehrer-separate-table.md) | Fachlehrer als eigene Tabelle (nicht KL-Sub-Rolle) |

(ADRs 0001/0002 wurden vor M4 vergeben.)

---

## Feature-Referenzen

| Doc | Inhalt |
|---|---|
| [`features/extensions-2026-06.md`](features/extensions-2026-06.md) | Erweiterungen-Batch 2026-06: Schulen-Dropdown, Klassen-Details/Edit, User-Dashboard + Edit-Modus, Klassen-PW-Reset, AD-Verbindungstest, Einzelschüler-Übergang, Per-User-Einstellungen, Rolle Fachlehrer |

---

## Setup-Scripts

| Script | Was tut es? |
|---|---|
| [`scripts/install-magister.sh`](../scripts/install-magister.sh) | Interaktiver End-to-End-Installer (Ubuntu/Debian): erzeugt Secrets + argon2-Hash, schreibt `.env`, startet den Stack. `--mode prod` (HTTPS/FQDN) oder `--mode dev` (HTTP/IP). Idempotent (bewahrt Secrets). |
| [`scripts/magister-cli`](../scripts/magister-cli) | Kleine Ops-CLI (z.B. Password-Hashing) |
