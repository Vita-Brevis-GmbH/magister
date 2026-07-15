# Demo Runbook

How to spin up a Magister demo on a fresh VM in ~10 minutes, with seed
data so every screen has something to show.

## Prerequisites

- A Linux host with Docker + Docker Compose v2.
- One pre-built `v0.1.0-demo` (or later) tag on the repo, which triggered
  the `release.yml` workflow and produced `ghcr.io/vita-brevis-gmbh/magister-{api,web}:latest`
  on GHCR. (Without a tag, `docker compose pull` finds nothing.)
- For a LAN/IP demo you do **not** need DNS or a public cert — use the
  installer's `--mode dev` (plain HTTP, reachable by IP). Only a public
  production demo needs a DNS name for Caddy's auto-TLS.

## 1 — Install (one command)

The installer prompts for the few values it needs, generates the secrets,
hashes the break-glass admin password (argon2id, plaintext never hits
disk), writes a correct `deploy/compose/.env`, and brings the stack up.

```bash
# LAN/IP demo over plain HTTP (no DNS, no cert warnings):
sudo ./scripts/install-magister.sh --mode dev
#   Hostname  -> the host's LAN IP (e.g. 172.25.8.27) or localhost
#   ACME mail -> any address (ignored in dev mode)
#   Admin pw  -> chosen interactively, min 12 chars

# Public demo with a real DNS name + auto-TLS:
sudo ./scripts/install-magister.sh --mode prod
```

When it finishes, the API logs
`Local admin seeded from MAGISTER_LOCAL_ADMIN_PASSWORD_HASH …` and the
URL is printed. Skip to step 2 (seed demo data).

> **Manual alternative.** If you'd rather write `.env` by hand:
> generate the four secrets with
> `python -c "import secrets; print(secrets.token_urlsafe(48))"`, then hash
> the admin password with the image (no checkout needed):
> ```bash
> printf '%s' 'YOUR_PASSWORD' | docker run --rm -i --entrypoint python \
>   ghcr.io/vita-brevis-gmbh/magister-api:latest \
>   -c 'import sys; from magister_api.auth.passwords import hash_password; print(hash_password(sys.stdin.readline().rstrip("\n")))'
> ```
> **Double every `$` to `$$`** when pasting the hash into `.env` — docker
> compose interpolates `$`, and an unescaped argon2 hash arrives corrupted
> (login then fails silently). Bring the stack up with
> `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`
> (dev) or `docker compose up -d` (prod).

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

1. **Open the printed URL + `/login`** — `http://<host-ip>/login` in dev
   mode, `https://<your-host>/login` in prod. Only the local form is
   visible (OIDC isn't configured yet). In dev, use `http://` explicitly
   and clear any stale cookies for the host if a previous HTTPS attempt
   left some.
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
- **Caddy can't get a cert / `ERR_SSL_PROTOCOL_ERROR` on an IP**: you're
  running the prod stack against a non-resolvable host or a bare IP —
  Let's Encrypt can't issue for those. Use `--mode dev` (plain HTTP via
  `docker-compose.dev.yml`) for LAN/IP demos instead.
- **Login bounces back to the form with no error (dev)**: a stale
  `Secure` session cookie from an earlier HTTPS attempt. `--mode dev`
  already disables `Secure`; clear the host's cookies and use `http://`.

## What the demo proves

| Capability | Where to show it |
|---|---|
| Day-1 onboarding without OIDC | Local-admin login |
| Operator UX for Entra config | `/admin/settings` (no restart!) |
| KL workflow | `/classes/$id` student management |
| Schulleitung workflow | Create class / assign KL |
| Audit + encryption | DB query: `SELECT pgp_sym_decrypt(payload, ...) FROM audit_events` |
| i18n | URL `?lng=fr` or browser language detection |
