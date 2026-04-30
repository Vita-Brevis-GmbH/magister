# Setup-Runbook · Magister Backend Foundation

Dieses Runbook deckt die Erst-Inbetriebnahme der Magister-API ab — Auth + Audit
sind bereits implementiert (Issues #1, #2). User-Listing, Klassen etc. kommen
in den Folge-Issues.

## 1. Voraussetzungen

- Linux-Server (Compose-Stack später; lokal reicht Docker oder lokales Postgres)
- PostgreSQL 16 mit `pgcrypto`-Extension
- Python 3.12 (`uv` empfohlen)
- Erreichbarer Entra-ID-Tenant + App-Registrierung

## 2. App-Registrierung in Entra ID

1. Azure-Portal → **Microsoft Entra ID → App registrations → New registration**
2. Name: `Magister-<Schulträger>`
3. Redirect URI (Web): `https://magister.<schultraeger>.ch/auth/callback`
4. Nach dem Anlegen:
   - **Application (client) ID** → `MAGISTER_OIDC_CLIENT_ID`
   - **Directory (tenant) ID** → wird Teil von `MAGISTER_OIDC_ISSUER`
5. **Certificates & secrets → New client secret**
   → `MAGISTER_OIDC_CLIENT_SECRET`
6. **Authentication → ID tokens** aktivieren (für Authorization-Code-Flow).
7. **API permissions**: `openid`, `profile`, `email` (Microsoft Graph, delegiert).

## 3. Datenbank vorbereiten

```bash
sudo -u postgres psql <<'SQL'
CREATE USER magister WITH PASSWORD '<starkes-pw>';
CREATE DATABASE magister OWNER magister;
\c magister
CREATE EXTENSION IF NOT EXISTS pgcrypto;
SQL
```

> `pgcrypto` legt die SQL-Funktionen `pgp_sym_encrypt` / `pgp_sym_decrypt` an,
> die Magister für die column-level Verschlüsselung von `audit_events.payload`
> nutzt.

## 4. Environment

`.env` (oder Compose-Secrets) — alle Keys haben Prefix `MAGISTER_`:

```
MAGISTER_ENVIRONMENT=production
MAGISTER_LOG_LEVEL=INFO

MAGISTER_DATABASE_URL=postgresql+asyncpg://magister:<pw>@db:5432/magister

# Symmetric key for pgcrypto pgp_sym_encrypt — generate with:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
# Once set, NEVER rotate without a planned migration: existing audit rows
# can no longer be decrypted otherwise.
MAGISTER_AUDIT_KEY=<urlsafe-base64-48-bytes>

# Server-side session signing key + CSRF HMAC key. Independent rotation OK.
MAGISTER_SESSION_SECRET=<urlsafe-base64-32-bytes>
MAGISTER_CSRF_SECRET=<urlsafe-base64-32-bytes>

# OIDC against Entra
MAGISTER_OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0
MAGISTER_OIDC_CLIENT_ID=<app-client-id>
MAGISTER_OIDC_CLIENT_SECRET=<app-client-secret>
MAGISTER_OIDC_REDIRECT_URI=https://magister.<schultraeger>.ch/auth/callback

# Bootstrap admin(s) — comma-separated UPNs that get role=admin on first login.
# Remove from .env once the first admin has actually logged in (role is then
# persistent in DB).
MAGISTER_BOOTSTRAP_ADMINS=admin1@<schultraeger>.ch,admin2@<schultraeger>.ch

# AD details (consumed by issue #3 / #7)
MAGISTER_AD_DCS=dc1.<schule>.local,dc2.<schule>.local
MAGISTER_AD_BIND_DN=CN=svc-magister,OU=ServiceAccounts,DC=<schule>,DC=local
MAGISTER_AD_BIND_PASSWORD=<ad-svc-pw>
```

## 5. Migrations ausführen

```bash
cd apps/api
uv sync --extra dev
uv run alembic upgrade head
```

Der erste Migrations-Lauf legt an: `schools`, `ad_user_cache`, `sessions`,
`role_assignments`, `audit_events` (mit verschlüsseltem `payload bytea`).

> Magister fährt Migrationen NICHT automatisch beim Containerstart hoch — das
> ist Absicht (CLAUDE.md: kein Auto-Migrate in Production).

## 6. API starten

Lokal:
```bash
uv run uvicorn magister_api.main:app --host 0.0.0.0 --port 8000
```

Compose: kommt mit dem Stack-PR (#X). Bis dahin: lokal/Systemd-Unit nach Wahl.

## 7. Bootstrap-Login durchspielen

1. Browser auf `https://magister.<schultraeger>.ch/auth/login`
2. Entra-Login mit dem in `MAGISTER_BOOTSTRAP_ADMINS` gelisteten UPN
3. Redirect zurück nach `/auth/callback?code=...` → API tauscht den Code,
   erkennt Bootstrap-UPN, setzt Session-Cookie (`magister_session`) und
   CSRF-Cookie (`magister_csrf`).
4. `GET /auth/me` antwortet mit `is_admin: true, roles: ["admin"]`.
5. Audit-Trail in `audit_events`: ein `login`-Event und ein `role_granted`-Event.

Verifikation aus der DB:
```sql
SELECT id, action, actor_upn, ts FROM audit_events ORDER BY id;
-- payload ist bytea-encrypted; Decrypt nur über den AuditService:
--   await AuditService(session, settings).read(event_id)
```

## 8. Health-Check

```bash
curl https://magister.<schultraeger>.ch/healthz
# { "status": "ok", "version": "0.1.0" }
```

## 9. Edge-Cases

| Problem | Symptom | Fix |
|---------|---------|-----|
| `audit_events` schreiben schlägt mit `function pgp_sym_encrypt does not exist` fehl | `pgcrypto` nicht installiert | `CREATE EXTENSION pgcrypto;` als Superuser im DB-Schema |
| `/auth/callback` → 403 `user_not_synced` | UPN ist nicht in `MAGISTER_BOOTSTRAP_ADMINS` und der periodische AD-Sync (#3) hat den User noch nicht erfasst | Erst `MAGISTER_BOOTSTRAP_ADMINS` benutzen oder den Sync abwarten |
| `RuntimeError: Missing required runtime secrets` beim Container-Start | Eine der Required-Vars (`MAGISTER_AUDIT_KEY`, `MAGISTER_SESSION_SECRET`, `MAGISTER_CSRF_SECRET`) fehlt | `.env` ergänzen, Container neu starten |
| Audit-Logs lassen sich nicht lesen | `MAGISTER_AUDIT_KEY` wurde rotiert | Keine Lösung ausser Restore: existierende Audit-Rows sind mit dem alten Key verschlüsselt — Schlüssel aus Backup wiederherstellen |
