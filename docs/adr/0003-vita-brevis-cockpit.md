# ADR 0003: Vita Brevis Cockpit als separates Ops-Tool

**Status:** Akzeptiert · 2026-06-02 · **umgesetzt 2026-11-11:** ausgelagert nach
`Vita-Brevis-GmbH/vitabrevis-cockpit` (siehe Nachtrag unten)
**Kontext:** M4 — Scale & Operations Maturity

## Problem

Mit wachsender Zahl an Schulträgern braucht das Ops-Team von Vita Brevis einen zentralen Überblick: Welche Instanz läuft? Welche Version ist deployed? Welche braucht ein Update? Heute manuell per SSH und Browser — skaliert nicht über ~5 Instanzen hinaus.

## Entscheidung

Wir bauen ein separates Tool **Vita Brevis Cockpit**:

1. **Eigenes Code-Subtree** unter `cockpit/` im Magister-Repo, später extrahiert nach `github.com/vita-brevis-gmbh/vita-brevis-cockpit` via `git subtree split` sobald GitHub-Org-Permissions für API-basierte Repo-Erstellung verfügbar sind.
2. **Eigener Stack** (FastAPI + React + Postgres), aber identische Konventionen wie Magister — Onboarding-Reibung minimal.
3. **Bootstrap-Token-Auth** (nicht OIDC) — Cockpit läuft hinter VPN/Tailscale, max. 5 Ops-User. Pragmatischer als Full-OIDC-Setup.
4. **Read-mostly auf Magister-Daten** — Cockpit ruft nur `/api/healthz` (liefert Status + Version) der Magister-Instanzen ab. **Kein** direkter DB-Zugriff zu Magister-Postgres-Instanzen.

## Konsequenzen

**Positiv:**
- Klare Trennung Ops-Tool vs. Schul-Tool (keine RBAC-Vermischung)
- Cockpit-Crash bringt keine Magister-Instanz herunter
- Schulträger sehen das Cockpit nie

**Negativ:**
- Zwei Codebases zu pflegen
- Cross-Repo Versions-Bumps brauchen Koordination (in M4.3 lösen wir das via signiertem Manifest)

## Alternativen verworfen

- **Cockpit als Magister-Subapp**: würde RBAC-Modell aufweichen (Vita-Brevis-Ops vs. Schulleitung in derselben App)
- **Grafana + Custom-Plugin**: zu schwergewichtig für 5 Instanzen, schlechte UX für Update-Trigger

## Nachtrag 2026-11-11 – ausgelagert

- `cockpit/` ist mit `git subtree split` (Verlauf erhalten) nach
  `Vita-Brevis-GmbH/vitabrevis-cockpit` (privat) umgezogen. Dazu kamen die Skripte
  `install-cockpit.sh`, `bootstrap-cockpit-token.sh` und die Runbooks `install-cockpit.md` und
  `cockpit-update-runner.md`.
- Das Cockpit löst das bisherige Cockpit in Magister ab und bleibt eng mit Magister verbunden:
  - gleiche Konventionen;
  - Magister ist das erste Produkt;
  - Release über GHCR und ein Manifest je Kanal.
- Es verwaltet künftig auch Automato, NetBox und Keycloak.
- Entscheide und Phasen stehen im Cockpit-Repo: ADR 0001/0002 und `ROADMAP.md`.
- Für Magister kommen dazu:
  - Anmeldung über Keycloak (Realm des Kunden, mit Entra verbunden), hinter dem Kundenportal
    unter `<kunde>-um`;
  - später ersetzt ein Host-Agent den SSH-Update-Runner.
- Ein Cockpit, das bisher aus einem Magister-Klon unter `/opt/cockpit/src` lief, zieht nach dem
  Runbook `install-cockpit.md` im Cockpit-Repo um (Abschnitt „Umzug“, die Datenbank bleibt).
