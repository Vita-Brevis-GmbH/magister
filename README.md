# Magister

> User & class management for schools
> Part of **Schola Levis** by **Vita Brevis**

**Status:** M1 — Initial Scaffolding. Noch kein Implementierungs-Code.

## Was Magister macht

Magister ist ein webbasiertes Schulverwaltungs-Tool für Schweizer Schulen. Es bindet das on-prem Active Directory eines Schulträgers an, lässt Klassenlehrer:innen ihre Klassen verwalten und Passwörter ihrer Schüler:innen zurücksetzen — auditierbar und mehrsprachig.

## Features (M1)

- Auflistung aller AD-User pro Schule, gefiltert nach Schul-Scope
- Klassifizierung von AD-Lehrern als Klassenlehrer:in mit Sub-Rollen (Haupt-KL · Co-KL · Stellvertretung)
- Schulklassen-Definition (lebende Klassen, Audit-Historie)
- Zuweisung von Klassenlehrer:innen und Schüler:innen zu Klassen
- Passwort-Reset für Schüler:innen durch deren KL — Generate- oder Manual-Mode, Forced-Change-Flag, vollständiges Audit
- OIDC-Login gegen Entra ID inkl. Bootstrap-Admin via Env-Var
- RBAC: Admin · Schulleitung · Klassenlehrer
- Mehrsprachige UI: DE · FR · IT · EN

## Tech-Stack

- **Backend** — Python 3.12 + FastAPI · ldap3 · SQLAlchemy + Alembic · PostgreSQL 16
- **Frontend** — React + Vite + TanStack + shadcn/ui · i18next
- **Auth** — OIDC gegen Entra ID · ldap3 für AD-Writes (LDAPS, ServerPool, sealed/signed)
- **Deploy** — Docker Compose · Caddy 2 · Images via GHCR
- **CI** — GitHub Actions

Details: [`ARCHITECTURE.md`](ARCHITECTURE.md), Anforderungen: [`SPEC.md`](SPEC.md), Roadmap: [`ROADMAP.md`](ROADMAP.md), Coding-Konventionen: [`CLAUDE.md`](CLAUDE.md).

## Quickstart (Platzhalter)

> Setup-Schritte werden mit M1 finalisiert. Skizze:

```bash
# Voraussetzungen: Docker, Docker Compose, gh, git
git clone https://github.com/vita-brevis/magister.git
cd magister
cp deploy/compose/.env.example deploy/compose/.env
# .env editieren: MAGISTER_BOOTSTRAP_ADMINS, MAGISTER_AD_DCS, OIDC-Client-ID/Secret
docker compose -f deploy/compose/docker-compose.yml up -d
```

Erster `MAGISTER_BOOTSTRAP_ADMINS`-UPN loggt sich via Entra ein und richtet die erste Schule ein.

## Branch-Strategie

- `main` ist protected (PR-Reviews, Status-Checks, linear history)
- Feature-Branches: `feat/<issue>-<slug>` · `fix/<issue>-<slug>` · `chore/<slug>` · `docs/<slug>`
- Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `ci:`)
- Squash-Merge als Default

## Lizenz

Magister steht unter der **GNU Affero General Public License v3.0** — siehe [`LICENSE`](LICENSE).
Copyright (C) 2026 Vita Brevis.

## Brand

**Vita Brevis** ist die Herausgeberin. **Schola Levis** ist die Produktlinie für Schul-Software. **Magister** ist das M1-Produkt: Schweizer Schulverwaltung für Volksschule-Schulträger.
