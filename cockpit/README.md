# Vita Brevis Cockpit

> Internes Ops-Dashboard für die Verwaltung von Magister-Instanzen über mehrere Schulträger hinweg.
> Teil von **Schola Levis** by **Vita Brevis**.

**Status:** M4-Foundation — wird später in ein eigenes Repo (`vita-brevis-cockpit`) extrahiert via `git subtree split`.

## Zweck

Das Cockpit ist das interne Werkzeug des Vita-Brevis-Ops-Teams. Es:

- Listet alle verwalteten Magister-Instanzen (1 Schulträger = 1 Instanz)
- Pollt periodisch `/api/health` und `/api/version` jeder Instanz
- Zeigt aktuell deployte Version vs. neueste verfügbare Version (`stable`/`latest` Channel)
- Triggered Updates über einen Webhook auf die Zielinstanz (M4 Schritt 2)

## Nicht-Ziele

- **Kein** Replacement für Magister-RBAC: Schulträger administrieren ihre User weiter in der Magister-UI.
- **Keine** Schüler-/Lehrerdaten — das Cockpit speichert nur Instanz-Metadaten (URL, Version, Health-Timestamp).

## Stack

| Layer | Choice |
|-------|--------|
| Backend | Python 3.12 + FastAPI |
| ORM | SQLAlchemy 2 (async) + Alembic |
| Auth | Bootstrap-Token + Basic-Auth (intern only, hinter VPN/Tailscale) |
| Frontend | React + Vite + TanStack Query + Tailwind/shadcn |
| Database | PostgreSQL 16 |
| Deployment | Docker Compose |

## Layout

```
cockpit/
  api/                FastAPI backend
    cockpit_api/
      routers/        Endpoints (instances, health, versions)
      services/       Health-Poller, Version-Fetcher
      models/         SQLAlchemy
      schemas/        Pydantic
    alembic/          Migrationen
    tests/
  web/                React frontend
  deploy/             docker-compose.yml
```

## Roadmap im Cockpit

- **M4.1 (jetzt):** Foundation — Instanz-Liste, Health-Polling, Version-Anzeige
- **M4.2:** Update-Trigger (Webhook → Magister-Instanz pulled neues Image)
- **M4.3:** Update-Channels `stable` / `latest` mit Roll-Back-Snapshot
