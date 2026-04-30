# Magister · CLAUDE.md

**Magister** is a webbased school administration tool for Swiss schools.
Part of **Schola Levis** by **Vita Brevis**.

## Project context

Magister manages users (teachers + students from on-prem AD), classes, class-teacher assignments, and student password resets — for one Schulträger/Gemeinde at a time. Schools are first-class scope entities. Magister-DB is master for the class structure; AD is source of truth for user identities (objectGUID).

## Tech stack

| Layer | Choice |
|-------|--------|
| Backend | Python 3.12 + FastAPI + Pydantic v2 |
| ORM / Migrations | SQLAlchemy 2 (async) + Alembic |
| AD integration | ldap3 with ServerPool (LDAPS, sealed/signed bind) |
| Auth (teachers/admin) | OIDC against Entra ID (MFA via Conditional Access) |
| Frontend | React + Vite + TanStack Query/Router + shadcn/ui |
| i18n | i18next (de · fr · it · en) |
| Database | PostgreSQL 16 (JSONB for audit payloads) |
| Reverse proxy | Caddy 2 (Auto-TLS via ACME) |
| Deployment | Docker Compose; images on GHCR |
| CI | GitHub Actions |

## Build / test / lint

```bash
# Backend (apps/api)
uv sync
uv run uvicorn magister_api.main:app --reload
uv run pytest
uv run ruff check
uv run ruff format
uv run pyright

# Frontend (apps/web)
pnpm install
pnpm dev
pnpm test
pnpm lint
pnpm build

# Full stack (Compose)
docker compose -f deploy/compose/docker-compose.yml up
```

## Niemals (hard rules — CI fails if violated)

- **Niemals** Credentials, Passwörter, Session-Tokens, OIDC-Token oder LDAP-Bind-Strings loggen
- **Niemals** Plain-LDAP — immer LDAPS auf Port 636 mit sealed+signed bind
- **Niemals** raw SQL aus Routern/Controllern; nur via Repository-Layer
- **Niemals** `print()` im Backend-Code; immer der konfigurierte Logger
- **Niemals** Schul-Scope-Filter umgehen — jede DB-Query, die personenbezogene Daten liest, MUSS `school_id`-gefiltert sein (Ausnahme nur mit Code-Kommentar `# scope-bypass: <reason>`)
- **Niemals** synchrone LDAP-Calls im async Request-Pfad — immer in `run_in_threadpool` wrappen
- **Niemals** eine schreibende Operation ohne korrespondierendes Audit-Event committen
- **Niemals** hardcodierte UI-Strings — alle Texte als i18n-Keys

## Immer (positive rules)

- **Immer** RBAC-Dependency an jedem geschützten Endpoint (`Depends(require_role(...))`)
- **Immer** Audit-Event bei Mutation (`audit_events`-Tabelle, Felder: actor, action, target, payload, ip, request_id, ts)
- **Immer** `audit_events.payload` über den Audit-Service-Decrypt-Helper lesen — nie direkt `SELECT payload FROM audit_events` (column ist via `pgcrypto` encrypted-at-rest)
- **Immer** DB-Schema-Änderungen via Alembic-Migration (kein Auto-Migrate in Production)
- **Immer** Type-Hints; pyright strict mode
- **Immer** UPN- und objectGUID-Validation an System-Boundary (Pydantic-Validator)
- **Immer** explizite Transaktions-Grenzen via SQLAlchemy `async with session.begin()`
- **Immer** Fehler an User in der von ihm gewählten Sprache (i18n via `Accept-Language` resp. User-Profil)

## Coding-Konventionen

- Python: ruff Defaults + pep8-naming, Linelength 100, Imports sortiert; Docstrings nur wo das *Warum* nicht offensichtlich ist
- TypeScript: ESLint + Prettier; Functional Components, kein Class-Component; Tailwind via shadcn/ui; Komponenten in `src/components/`, Routes in `src/routes/`, API-Hooks in `src/api/`
- Tests: pytest (`tests/unit`, `tests/integration`), ldap3 MockServer für AD-Tests; vitest + Testing Library im Frontend
- Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `ci:`)

## Source layout

```
apps/
  api/              FastAPI backend
    magister_api/
      routers/      HTTP-Endpoints (1 file per resource)
      services/     Business-Logic, Mehr-Tabellen-Operationen, AD-Calls orchestrieren
      repositories/ DB-Access; school_id-Filter zentral
      ad/           ldap3-Layer + ServerPool + Reset-Mechanik
      auth/         OIDC, Sessions, RBAC-Dependencies, Bootstrap
      models/       SQLAlchemy
      schemas/      Pydantic Request/Response
      audit/        Audit-Middleware + Event-Builder
    alembic/        DB-Migrationen
    tests/
  web/              React frontend
    src/components/
    src/routes/
    src/api/
    src/i18n/       Locale-Files: de.json, fr.json, it.json, en.json
    src/lib/
deploy/
  compose/          docker-compose.yml + .env.example
  caddy/            Caddyfile-Template
  ansible/          Vita-Brevis-Ops Playbooks
docs/
  adr/              Architecture Decision Records
  runbooks/         Ops-Runbooks
scripts/            CLI-Tools (z.B. magister-cli)
```

## Querverweise

- Spec / Anforderungen: `SPEC.md`
- Architektur-Diagramm + Sicherheitsmodell: `ARCHITECTURE.md`
- Roadmap: `ROADMAP.md`
- ADRs: `docs/adr/`
