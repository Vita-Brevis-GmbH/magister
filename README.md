# Magister

> User & class management for schools
> Part of **Schola Levis** by **Vita Brevis**

## Was Magister macht

Magister ist ein webbasiertes Schulverwaltungs-Tool für Schweizer Schulen
auf Stufe Schulträger / Gemeinde. Es bindet das on-prem Active Directory
einer Schulträgers an, lässt Klassenlehrer:innen ihre Klassen verwalten
und Passwörter ihrer Schüler:innen zurücksetzen — auditierbar,
mehrsprachig und ohne dass irgend ein Setup-Schritt SSH auf den Server
verlangt: OIDC + AD-Konfiguration sind nach dem ersten Boot komplett im
Admin-GUI editierbar.

## Was drin ist

- **OIDC-Login gegen Entra ID** für Lehrpersonen + Admins (PKCE,
  MFA-fähig über Conditional Access)
- **Lokaler Break-Glass-Admin** (argon2id-gehasht) für Day-1-Setup und
  Recovery, wenn Entra nicht erreichbar ist
- **Admin-GUI** für OIDC- + AD-Konfiguration; Secrets pgcrypto-verschlüsselt
  in der DB, Reload ohne Neustart
- **AD-Sync** aller Schul-User (LDAPS · ServerPool · sealed/signed bind);
  per-Schule-Scope aus dem OU-Pfad abgeleitet
- **Klassenverwaltung**: anlegen, umbenennen, archivieren (Soft-Delete);
  KL/Co-KL/Stellvertretung mit Gültigkeitsfenstern
- **Schüler-Memberships** mit Mid-Year-Wechsel (alte Mitgliedschaft klammert
  automatisch auf `valid_from − 1s`)
- **Schüler-Passwort-Reset** durch den KL (Generate-Mode mit einmaliger
  PW-Anzeige + Copy-to-Clipboard, oder Manual-Mode mit Policy-Gating);
  Force-Change-Flag setzt `pwdLastSet=0` im AD
- **RBAC** Admin · Schulleitung · Klassenlehrer:in; per-Endpoint
  Dependency-Injection
- **Audit-Pipeline** mit pgcrypto-verschlüsseltem JSON-Payload + Schlüssel-Allowlist
  gegen versehentliches Logging von Credentials
- **Mehrsprachige UI**: DE · FR · IT · EN (DE source-of-truth; FR/IT sind
  Stub-Übersetzungen, vor M3 Produktion durch Native-Reviewer noch zu
  prüfen)

## Tech-Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12 · FastAPI · Pydantic v2 |
| ORM / Migrations | SQLAlchemy 2 (async) + Alembic |
| AD-Integration | ldap3 mit ServerPool (LDAPS · sealed/signed bind) |
| Auth | OIDC gegen Entra ID + lokaler Break-Glass-Admin (argon2id) |
| Frontend | React 18 · Vite 6 · TanStack Router/Query · shadcn-Style UI |
| i18n | i18next (de/fr/it/en) |
| Database | PostgreSQL 16 (JSONB + pgcrypto für Audit-Payload + Secrets) |
| Reverse-Proxy | Caddy 2 (Auto-TLS via ACME) |
| Deployment | Docker Compose · GHCR-Images |
| CI | GitHub Actions |

Details: [`ARCHITECTURE.md`](ARCHITECTURE.md) · Anforderungen: [`SPEC.md`](SPEC.md)
· Roadmap: [`ROADMAP.md`](ROADMAP.md) · Coding-Konventionen: [`CLAUDE.md`](CLAUDE.md).

---

## Installation auf einem Ubuntu / Debian Server

Getestet gegen Ubuntu 24.04 LTS und Debian 12. Voraussetzung: Root- oder
sudo-Zugang.

> **Tipp:** Für eine end-to-end-Anleitung mit allen Befehlen, Firewall-
> Setup, AD-Delegationen, Mail-Domains, SMI-Rollen-Grant und
> Smoke-Tests siehe [`docs/runbooks/install-ubuntu.md`](docs/runbooks/install-ubuntu.md).
> Die Kurzfassung unten reicht für eine Demo.

### 1 — Hostname + DNS

Magister braucht einen FQDN, auf den ein DNS-A/AAAA-Record für die
öffentliche IP zeigt — Caddy holt darüber Let's-Encrypt-Zertifikate.
Für reine LAN-Demos kannst du `acme_ca https://acme-staging-v02.api.letsencrypt.org/directory`
in `deploy/caddy/Caddyfile` einkommentieren (oder per `tls internal`
self-signed laufen) — siehe Demo-Runbook unten.

### 2 — Docker + Compose installieren

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git

# Docker's official repository:
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/$(. /etc/os-release && echo "$ID") \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER
newgrp docker  # oder neu einloggen
```

Auf Debian 12: ersetze `ubuntu` durch `debian` in den beiden URL-Zeilen.

### 3 — Repo + Konfiguration

```bash
git clone https://github.com/vita-brevis-gmbh/magister.git
cd magister/deploy/compose
cp .env.example .env
```

`.env` ausfüllen — Minimal-Set:

```env
MAGISTER_PUBLIC_HOSTNAME=magister.example.ch     # DNS-Name, der auf den Server zeigt
MAGISTER_ACME_EMAIL=ops@example.ch               # Let's-Encrypt Kontakt
POSTGRES_PASSWORD=<setze ein starkes PW>

# 3× je ein zufälliges Geheimnis erzeugen:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
MAGISTER_AUDIT_KEY=<48-byte url-safe random>
MAGISTER_SESSION_SECRET=<48-byte url-safe random>
MAGISTER_CSRF_SECRET=<48-byte url-safe random>
```

Für den Day-1-Login: einen Break-Glass-Admin-Account erzeugen. Das
Plaintext-Passwort landet nirgends auf der Disk; nur der argon2id-Hash
liegt im `.env`:

```bash
# Aus einem Checkout heraus mit uv installiert:
cd ../../apps/api && uv run ../../scripts/magister-cli hash-password
# Password: ********
# Confirm:  ********
# $argon2id$v=19$m=65536,t=3,p=4$...
```

Den Hash + Username ins `.env`:

```env
MAGISTER_LOCAL_ADMIN_USERNAME=admin
MAGISTER_LOCAL_ADMIN_PASSWORD_HASH=$argon2id$v=19$...
```

**OIDC- und AD-Konfiguration sind in M1.5 nicht mehr nötig im `.env`** —
sie werden im Admin-GUI eingetragen, sobald du eingeloggt bist. Wer
trotzdem einen Wert setzt: der Lifespan-Seed übernimmt ihn beim ersten
Boot in die DB, danach sind die Env-Vars optional.

### 4 — Stack hochfahren

```bash
cd ../deploy/compose
docker compose pull
docker compose up -d
docker compose logs -f magister-api
```

Du solltest u.a. sehen:

```
WARNING  Local admin seeded from MAGISTER_LOCAL_ADMIN_PASSWORD_HASH …
INFO     Application startup complete
```

Caddy holt im Hintergrund das ACME-Zertifikat; nach 30-60s ist
`https://<dein-hostname>/login` erreichbar.

### 5 — Erste Anmeldung + OIDC einrichten

1. **`https://<dein-hostname>/login`** öffnen. Du siehst die lokale
   Login-Form (OIDC ist noch nicht konfiguriert).
2. Mit `admin` + dem Klartext-Passwort aus Schritt 3 anmelden.
3. Im Header **Administration → Systemeinstellungen** öffnen.
4. Entra ID konfigurieren: Issuer-URL, Client-ID, Client-Secret,
   Redirect-URI (`https://<hostname>/api/auth/callback`), Scopes,
   Bootstrap-Admin-UPNs.
5. AD eintragen: Domain-Controller (komma-getrennt), Bind-DN,
   Bind-Passwort, Such-Basis (z. B. `OU=Users,DC=schule,DC=local`),
   Sync-Intervall.
6. Speichern. Der OIDC- + AD-Client wird bei nächsten Request automatisch
   neu instanziiert (App.state-Cache via `version`-Counter).
7. **Abmelden** und mit dem realen Entra-Account neu einloggen.
   Bootstrap-Admin-UPNs bekommen beim ersten OIDC-Login automatisch
   `role=admin`.
8. Optional: unter **Administration → Lokales Admin-Konto** den Local-Admin
   `enabled=false` togglen. Bleibt als Break-Glass-Account in der DB.

Detailliertes Upgrade-Szenario aus M1 → M1.5:
[`docs/runbooks/upgrade-to-m1.5.md`](docs/runbooks/upgrade-to-m1.5.md).

### 6 — Backup

Der mitgelaufende `pg-backup`-Sidecar schreibt täglich um 02:15 UTC
`pg_dump`s nach `/var/backups/magister` im Container-Volume. Cron-Schedule
+ Retention sind via `BACKUP_CRON` + `BACKUP_RETENTION_DAYS` im `.env`
einstellbar. Volume nach off-host syncen ist Ops-Aufgabe.

---

## Demo-Rollout (zum Zeigen)

Frische VM → klickbarer Demo in ~10 Minuten mit Beispiel-Schule,
Lehrpersonen, Schüler:innen und Klassen.

```bash
# Voraussetzung: Schritte 1-4 oben sind durch.

docker compose exec magister-api python -m magister_api.cli.seed_demo
```

Das seedet:

- 1 Demo-Schule (`BSP — Schule Beispiel`)
- 3 Lehrpersonen + 12 Schüler:innen im `ad_user_cache`
- 2 aktive Klassen (`4a`, `4b`), je eine KL
- 12 Schüler-Memberships, alternierend zwischen den Klassen

Das CLI ist idempotent — zweiter Aufruf zeigt `=` für jede Zeile,
ohne Duplikate. Auf einer DB mit existierenden Klassen weigert es sich,
es sei denn `--force` ist gesetzt.

**Walkthrough nach dem Seed:**

1. Local-Admin-Login → Dashboard
2. `/classes` → `4a` und `4b` sichtbar
3. Klick auf `4a` → KL-Liste (Anna Lehrer) + 6 Schüler:innen
4. KL/Schüler-Verwaltung demonstrieren (zuweisen, beenden, Mid-Year-Transfer)
5. `/users?kind=student` → "Passwort zurücksetzen"-Button pro Schüler:in
6. `/admin/settings` → OIDC-Issuer ändern und speichern (kein Restart!)

Vollständige Anleitung inkl. Troubleshooting + "was die Demo zeigt"-Matrix:
[`docs/runbooks/demo.md`](docs/runbooks/demo.md).

---

## Quellcode-Layout

```
apps/
  api/                FastAPI Backend (Python 3.12 + uv)
    magister_api/
      audit/          Audit-Middleware + Allowlist + pgcrypto-Service
      auth/           OIDC, Sessions, CSRF, RBAC, lokale Admin-Auth, Effective-Settings-Overlay
      ad/             ldap3-Client + ServerPool
      cli/            magister-cli subcommands (hash-password, seed-demo)
      models/         SQLAlchemy
      repositories/   DB-Access mit zentralem school_id-Filter
      routers/        HTTP-Endpoints (1 Datei pro Resource)
      schemas/        Pydantic Request/Response
      services/       Business-Logic, Mehr-Tabellen-Operationen
    alembic/          DB-Migrationen (0001 → 0006)
    tests/            unit + integration (Postgres-required)
  web/                React + Vite Frontend
    src/components/   shadcn-Style UI-Primitive + Layout + ResetPasswordModal
    src/routes/       TanStack file-based Routen
    src/api/          Typed Fetch + React-Query-Hooks
    src/i18n/         Locale-JSONs + i18next-Setup
deploy/
  compose/            docker-compose.yml + .env.example + pg-backup
  caddy/              Caddyfile-Template (Auto-TLS + /api-Split)
docs/
  runbooks/           Demo-Setup, Upgrade von M1 → M1.5
scripts/
  magister-cli        argon2-Hash + Demo-Seed
```

## Branch-Strategie + Beiträge

- `main` ist protected (PR-Reviews, Status-Checks, linear history)
- Feature-Branches: `feat/<slug>` · `fix/<slug>` · `chore/<slug>`
- Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `ci:`)
- Squash-Merge als Default

## Lizenz

Magister steht unter der **GNU Affero General Public License v3.0** — siehe [`LICENSE`](LICENSE).
Copyright (C) 2026 Vita Brevis.

## Brand

**Vita Brevis** ist die Herausgeberin. **Schola Levis** ist die Produktlinie
für Schul-Software. **Magister** ist das M1-Produkt: Schweizer
Schulverwaltung für Volksschule-Schulträger.
