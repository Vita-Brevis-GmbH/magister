# Vita Brevis Cockpit

> Internes Ops-Dashboard für die Verwaltung von Magister-Instanzen über mehrere Schulträger hinweg.
> Teil von **Schola Levis** by **Vita Brevis**.

**Status:** M4-Foundation — wird später in ein eigenes Repo (`vita-brevis-cockpit`) extrahiert via `git subtree split`.

## Zweck

Das Cockpit ist das interne Werkzeug des Vita-Brevis-Ops-Teams. Es:

- Listet alle verwalteten Magister-Instanzen (1 Schulträger = 1 Instanz)
- Pollt periodisch `/api/healthz` (Status + Version) jeder Instanz
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
      routers/        Endpoints (tenants, backups, offboarding, connector, instances)
      services/       Bereitstellung, Sicherung, Export, Health-Poller
      models/         SQLAlchemy
      schemas/        Pydantic
    alembic/          Migrationen
    tests/
  web/                React frontend
    src/api/          ein Modul je Ressource, plus client.ts
    src/components/   Bausteine (SecretOnce, Badge, ErrorBox, ProvisioningLog)
    src/routes/       Ansichten (Tenants, TenantDetail mit vier Reitern, Instances)
    src/lib/nav.ts    Navigation über den Hash
  deploy/             docker-compose.yml
```

## Zwei Entscheide zur Oberfläche

**Die Konsole ist auf Deutsch, ohne i18n.** CLAUDE.md verlangt „alle Texte als
i18n-Keys" — diese Regel schützt die *Kunden*-Oberfläche, die Lehrpersonen und
Schulleitungen in vier Sprachen bedient. Die Konsole hat zwei Benutzer, beide
bei Vita Brevis, beide deutschsprachig. Ein Übersetzungsgerüst für sie wäre
Aufwand ohne Empfänger, und jeder Text müsste zweimal gepflegt werden. Kommt je
ein französischsprachiger Operator dazu, ist das der Moment für i18next — nicht
vorher.

**Kein Router als Abhängigkeit.** `src/lib/nav.ts` löst die Navigation über den
Hash. Die Konsole hat vier Ansichten; ein Router (TanStack, wie in `apps/web`)
bringt Datenlader, typisierte Suchparameter und verschachtelte Layouts mit,
von denen hier nichts gebraucht wird. Der Hash statt des Pfades spart
zusätzlich die Server-Regel, die sonst alle Pfade auf `index.html` umschreiben
müsste — sonst wäre ein Neuladen von `/tenants/<id>` ein 404, und das merkt man
erst, wenn jemand einen Link weiterschickt.

## Prüfen

```bash
cd cockpit/web
pnpm install
pnpm build          # tsc (nur Prüfung, noEmit) + vite build
pnpm lint           # ESLint mit den react-hooks-Regeln
```

`noEmit` in `tsconfig.json` ist nicht Geschmack: ohne es schreibt `tsc` im
Build JavaScript **neben** die Quellen, und `src/App.js` landet beim nächsten
`git add .` im Repository.

## Roadmap im Cockpit

- **M4.1:** ✅ Foundation — Instanz-Liste, Health-Polling, Version-Anzeige
- **M4.2:** Update-Trigger (Webhook → Magister-Instanz pulled neues Image)
- **M4.3:** Update-Channels `stable` / `latest` mit Roll-Back-Snapshot

Dazu, aus der Mandantenfähigkeit (ADR-0013 bis ADR-0016):

- ✅ Kunden erfassen, bereitstellen, sperren, Rollenpasswort drehen
- ✅ Sicherungen, Aufbewahrung, Wiederherstellungen, Exporte
- ✅ AD-Connector: Agenten, Einmal-Token, Widerruf, Aufträge
- ✅ Kündigung in fünf Schritten mit Fristen und Schranken
- ⏳ Anmeldung über OIDC mit Hardware-Schlüssel (Entscheid E21) — bis dahin
  Bootstrap-Token
- ⏳ Ein Endpunkt, der **ausstehende** Einmal-Token nennt (ohne ihren Wert).
  Heute sieht man ein erzeugtes Token nach dem Ausblenden nirgends mehr; es
  verfällt nach 24 Stunden von selbst.
