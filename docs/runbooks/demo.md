# Demo Runbook

How to spin up a Magister demo on a fresh VM in ~10 minutes, with seed
data so every screen has something to show.

## Prerequisites

- A Linux host with Docker + Docker Compose v2.
- A DNS name pointing at the host (Caddy wants one for auto-TLS — for
  pure-LAN demos you can either point a hostname at the LAN IP or
  uncomment the `acme_ca` staging line in `deploy/caddy/Caddyfile`).
- One pre-built `v0.1.0-demo` (or later) tag on the repo, which triggered
  the `release.yml` workflow and produced `ghcr.io/vita-brevis-gmbh/magister-{api,web}:latest`
  on GHCR. (Without a tag, `docker compose pull` finds nothing.)

## 1 — Generate the local admin password

The local admin is a break-glass account that lets you sign in on Day 1
before OIDC is configured. The CLI ships argon2id hashing so plaintext
never lands on disk.

```bash
cd apps/api
uv run ../../scripts/magister-cli hash-password
# Password: ********
# Confirm:  ********
# $argon2id$v=19$m=65536,t=3,p=4$...
```

Copy the hash into `deploy/compose/.env`:

```env
MAGISTER_LOCAL_ADMIN_USERNAME=admin
MAGISTER_LOCAL_ADMIN_PASSWORD_HASH=$argon2id$v=19$...
```

## 2 — Fill in the rest of `.env`

```bash
cd deploy/compose
cp .env.example .env
# Edit:
#   MAGISTER_PUBLIC_HOSTNAME=demo.example.ch
#   MAGISTER_ACME_EMAIL=ops@example.ch
#   POSTGRES_PASSWORD=<choose>
#   MAGISTER_AUDIT_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
#   MAGISTER_SESSION_SECRET=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
#   MAGISTER_CSRF_SECRET=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
# OIDC / AD env vars: leave empty for the demo — they'll be set in the GUI later.
```

## 3 — Bring up the stack

```bash
docker compose up -d
docker compose logs -f magister-api  # watch for "Application startup complete"
```

The lifespan-seed creates the local admin row from the env vars and
logs `Local admin seeded from MAGISTER_LOCAL_ADMIN_PASSWORD_HASH …`.

## 4 — Seed demo data

Empty deployments come up with no classes and no AD-synced users, which
makes for a sad demo. Seed a fake school + teachers + students:

```bash
# Easiest path: exec into the running magister-api container.
docker compose exec magister-api python -m magister_api.cli.seed_demo
```

From a checkout (with the API venv) against the same DB:

```bash
cd apps/api
MAGISTER_DATABASE_URL=postgresql+asyncpg://magister:<pw>@localhost:5432/magister \
  uv run ../../scripts/magister-cli seed-demo
```

What it inserts:

- 1 school (`BSP — Schule Beispiel`)
- 3 teachers (Anna Lehrer, Beat Müller, Corinne Weber)
- 12 students (Aaron Amsler … Luca Lang, in `ad_user_cache`)
- 2 active classes (`4a`, `4b`) with one KL each (Anna → 4a, Beat → 4b)
- 12 active memberships, students alternated between the two classes

The CLI is idempotent — running it twice prints `=` for every row that
already exists. It refuses to run on a DB that already has any classes;
pass `--force` to override.

## 5 — Sign in + walk through

1. **Open `https://<your-host>/login`.** Only the local form is visible
   (OIDC isn't configured yet).
2. **Sign in** with the username + password from step 1.
3. **`/classes`** shows `4a` and `4b` with their KL.
4. **Click `4a`** → KL section + student list. Schulleitung / admin can
   reassign KL; KL can add/remove students. Try a mid-year transfer —
   moving a student from `4a` to `4b` automatically closes the previous
   membership.
5. **`/users`**, filter by Schüler:innen — every student row has a
   **"Passwort zurücksetzen"** button. The modal demos the generate
   flow (one-time-reveal + copy-to-clipboard) and the manual flow
   (≥ 12 char policy gating).
   - In demo mode the AD writeback will fail at the AdClient layer because
     no real AD is reachable; the GUI surfaces that as `ad_unavailable`.
     To exercise the full flow, point `MAGISTER_AD_*` at a real LDAPS
     target (or a mock-AD container) via `/admin/settings`.
6. **`/admin/settings`** — show how OIDC + AD config lives in the DB and
   secrets are encrypted at rest. Edit something (e.g. the AD sync
   interval), save, then watch the version counter bump. No restart.
7. **`/admin/local-admin`** — change-password form + disable toggle.
   Disable the local admin once Entra is wired up, then re-sign-in
   via OIDC.

## 6 — Tear down

```bash
docker compose down            # keep volumes
docker compose down --volumes  # nuke postgres + caddy data
```

## Troubleshooting

- **Empty `/classes` after seed**: the `as_admin` you signed in as needs
  to see across schools — the local admin is `role=admin`, school-scope
  empty, so it has cross-school visibility by design. If you signed in
  via Entra without the admin grant, you'll only see your own school's
  classes.
- **`POST /students/.../password-reset` returns 503 ad_unavailable**:
  expected with the seed. The students are in `ad_user_cache` but the
  reset writes to a real LDAPS — without one, AdClient bails. Either
  point at a real AD, or skip step 5 of the walkthrough.
- **Caddy can't get a cert**: for a LAN demo, uncomment the
  `acme_ca https://acme-staging-v02.api.letsencrypt.org/directory` line
  in `deploy/caddy/Caddyfile` to use Let's-Encrypt staging certs, or
  add a self-signed cert via `tls internal`.

## What the demo proves

| Capability | Where to show it |
|---|---|
| Day-1 onboarding without OIDC | Local-admin login |
| Operator UX for Entra config | `/admin/settings` (no restart!) |
| KL workflow | `/classes/$id` student management |
| Schulleitung workflow | Create class / assign KL |
| Audit + encryption | DB query: `SELECT pgp_sym_decrypt(payload, ...) FROM audit_events` |
| i18n | URL `?lng=fr` or browser language detection |
