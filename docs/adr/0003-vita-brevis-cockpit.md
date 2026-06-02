# ADR 0003: Vita Brevis Cockpit als separates Ops-Tool

**Status:** Akzeptiert · 2026-06-02
**Kontext:** M4 — Scale & Operations Maturity

## Problem

Mit wachsender Zahl an Schulträgern braucht das Ops-Team von Vita Brevis einen zentralen Überblick: Welche Instanz läuft? Welche Version ist deployed? Welche braucht ein Update? Heute manuell per SSH und Browser — skaliert nicht über ~5 Instanzen hinaus.

## Entscheidung

Wir bauen ein separates Tool **Vita Brevis Cockpit**:

1. **Eigenes Code-Subtree** unter `cockpit/` im Magister-Repo, später extrahiert nach `github.com/vita-brevis-gmbh/vita-brevis-cockpit` via `git subtree split` sobald GitHub-Org-Permissions für API-basierte Repo-Erstellung verfügbar sind.
2. **Eigener Stack** (FastAPI + React + Postgres), aber identische Konventionen wie Magister — Onboarding-Reibung minimal.
3. **Bootstrap-Token-Auth** (nicht OIDC) — Cockpit läuft hinter VPN/Tailscale, max. 5 Ops-User. Pragmatischer als Full-OIDC-Setup.
4. **Read-mostly auf Magister-Daten** — Cockpit ruft nur `/api/health` und `/api/version` der Magister-Instanzen ab. **Kein** direkter DB-Zugriff zu Magister-Postgres-Instanzen.

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
