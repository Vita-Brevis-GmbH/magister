# Upgrade Runbook — M1 → M1.5

M1.5 ships in two PRs that together move authentication and integration
configuration from environment variables into the database, and adds a
break-glass local admin so deployments can be set up before OIDC works.

| PR | Subject | Migration |
|----|---------|-----------|
| #19 (M1.5a) | Local break-glass admin account | `0005_local_admin` |
| (this PR, M1.5b) | DB-backed `app_settings` + admin GUI | `0006_app_settings` |

Both migrations are safe-additive — no destructive column renames or drops.

## What changes operationally

- `MAGISTER_OIDC_*` and `MAGISTER_AD_*` env vars are now **bootstrap-only**.
  On first boot the new lifespan-seed copies them into the `app_settings`
  row. From that point the DB is authoritative. After verifying the new GUI
  shows the right values, you can remove the env vars from `.env`.
- `MAGISTER_BOOTSTRAP_ADMINS` is also moved into the DB row alongside.
- `MAGISTER_AUDIT_KEY`, `MAGISTER_SESSION_SECRET`, `MAGISTER_CSRF_SECRET`
  and `MAGISTER_DATABASE_URL` remain mandatory env vars.
- The OIDC + AD clients now invalidate themselves automatically when the
  admin saves new settings — no container restart needed.
- A new `local_admins` row carries a single break-glass admin account. It
  is seeded from `MAGISTER_LOCAL_ADMIN_USERNAME` +
  `MAGISTER_LOCAL_ADMIN_PASSWORD_HASH` env on first boot only.

## Day-1 deployment (greenfield)

1. Generate the local admin password hash:
   ```bash
   cd apps/api && uv run ../../scripts/magister-cli hash-password
   ```
2. Copy the hash into `deploy/compose/.env` under
   `MAGISTER_LOCAL_ADMIN_PASSWORD_HASH`. Set
   `MAGISTER_LOCAL_ADMIN_USERNAME=admin` (or any name you prefer).
3. Bring up the stack:
   ```bash
   docker compose -f deploy/compose/docker-compose.yml up -d
   ```
4. Hit `https://<your-host>/login`. Sign in via the local form
   (username + password from step 1). You are now an admin.
5. Open `Administration → Systemeinstellungen` and enter your Entra OIDC
   issuer/client ID/client secret/redirect URI. Save.
6. Sign out, sign back in with Entra (the OIDC button is now visible). You
   should land in the dashboard.
7. Optional: in `Administration → Lokales Admin-Konto`, toggle the local
   admin to disabled now that OIDC works, keeping it as a documented
   break-glass that can be re-enabled by editing the DB.

## Upgrading an existing M1 deployment

1. **Pull the new image** (or rebuild from source).
2. **Add a local admin password** to the `.env`:
   ```bash
   cd apps/api && uv run ../../scripts/magister-cli hash-password
   # paste the output as MAGISTER_LOCAL_ADMIN_PASSWORD_HASH=...
   ```
3. **Restart**: `docker compose up -d`. On the first boot:
   - Alembic applies migrations 0005 + 0006.
   - The lifespan-seed copies your existing `MAGISTER_OIDC_*` /
     `MAGISTER_AD_*` env into the new `app_settings` row.
   - The local admin row is seeded from the hash.
   - The OIDC and AD configurations now live in the DB.
   - Watch for the WARN line in the logs:
     `app_settings seeded from MAGISTER_OIDC_* / MAGISTER_AD_* env`
4. **Verify in the GUI**: open `Administration → Systemeinstellungen` and
   confirm issuer/client ID/redirect URI/AD DCs/search base look right.
   The two secrets show `•••••••• (gesetzt)` — they're encrypted at rest
   in the same way `audit_events.payload` already was.
5. **(Optional) Remove env vars**: once you've verified the GUI, you can
   strip the following from `.env`:
   ```
   MAGISTER_OIDC_ISSUER, MAGISTER_OIDC_CLIENT_ID, MAGISTER_OIDC_CLIENT_SECRET,
   MAGISTER_OIDC_REDIRECT_URI, MAGISTER_BOOTSTRAP_ADMINS,
   MAGISTER_AD_DCS, MAGISTER_AD_BIND_DN, MAGISTER_AD_BIND_PASSWORD,
   MAGISTER_AD_USERS_SEARCH_BASE, MAGISTER_AD_SYNC_INTERVAL_MINUTES
   ```
   The container starts cleanly without them — the DB now owns the values.

## Recovery — Entra is down

1. Hit `/login`. The "Andere Anmeldung" disclosure shows a username +
   password form. Use the local admin credentials.
2. Once in, you can disable broken integrations or rotate secrets through
   the GUI.

If the local admin password is also lost, recover via the DB or via
`magister-cli` (a future subcommand will bake this in; for M1.5 the
manual recovery is `UPDATE local_admins SET password_hash = '<new>' WHERE id = 1;`).

## Rollback

`alembic downgrade -2` drops `app_settings` then `local_admins` and the
`sessions.auth_kind` column. The OIDC + AD clients then need their env
vars again — restore them from your `.env.example` template before the
restart.
