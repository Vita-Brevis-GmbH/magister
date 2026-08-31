# Runbook: strict 10-container split (ADR-0011)

Move from the single `magister-api` monolith to one container per function with a
**strict AD boundary**: only the `ad` container holds AD credentials and runs the
sync loop; every other container reaches AD through the `ad` container's internal
RPC. Same image, same Postgres — this is a deployment split, not a data split.

**Containers (10 API):** `magister-api` (platform base + `/api/*` catch-all +
migrator) · `magister-api-ad` · `-users` · `-settings` · `-templates` ·
`-classes` · `-departments` · `-imports` · `-reports` · `-devices`.

The whole boundary is **inert until you switch to `docker-compose.split10.yml`** —
without `MAGISTER_AD_RPC_URL` every process talks to AD directly, exactly as the
monolith does today.

## 1. Prerequisites

```bash
cd /opt/magister
git pull origin main

# One shared internal bearer for the AD-RPC channel (never exposed externally).
echo "MAGISTER_AD_RPC_SECRET=$(openssl rand -hex 32)" >> deploy/compose/.env
# (edit the file if the key already exists — keep exactly one line)
```

Confirm the AD credentials (`MAGISTER_AD_DCS`, `MAGISTER_AD_BIND_DN`,
`MAGISTER_AD_BIND_PASSWORD`, `MAGISTER_AD_USERS_SEARCH_BASE`) are set in `.env` —
they are consumed **only** by the `ad` container now.

## 2. Caddy routing

The per-container routes are committed at `deploy/caddy/split10-routes.caddy`
(do NOT run the generator on the server — its venv imports the full app incl.
WeasyPrint and will fail on a headless box). Paste that file's contents into
`deploy/caddy/Caddyfile` **immediately above** the generic
`handle_path /api/* { … }` block, inside the `{$MAGISTER_PUBLIC_HOSTNAME} …`
site block (specific routes must win). The internal `/internal/ad-rpc` surface
is deliberately **not** routed here — it stays reachable only
container-to-container.

Regenerate `docker-compose.split10.yml` + `split10-routes.caddy` only on a dev
machine (with the app deps installed) whenever modules or prefixes change:
`cd apps/api && uv run python ../../scripts/gen_split.py --strict`.

## 3. Bring up the split

**Pull first** — the split containers mount the new `ad`/`users`/`settings`/
`templates` modules; an image from before this change does not know them and
comes up unhealthy. This is the step most easily missed:

```bash
cd /opt/magister/deploy/compose
docker compose -f docker-compose.yml pull            # REQUIRED: fresh :latest with the new modules
docker compose -f docker-compose.yml -f docker-compose.split10.yml up -d
docker compose -f docker-compose.yml restart caddy   # reload the new routes
```

## 4. Verify

```bash
# Each container reports which modules it mounts + whether it owns the AD loop.
for c in magister-api magister-api-ad magister-api-users magister-api-reports; do
  echo "== $c =="
  docker compose -f docker-compose.yml -f docker-compose.split10.yml exec $c \
    python -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://localhost:8000/runtime')))"
done
```

Expect: only `magister-api-ad` shows `"scheduler_owner": true`; the others
`false`. Then exercise an AD write end-to-end (e.g. a password reset in the UI) —
it flows User-container → AD-RPC → `ad` container. Watch the `ad` logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.split10.yml logs -f magister-api-ad
```

A `403 ad_rpc_forbidden` there means `MAGISTER_AD_RPC_SECRET` differs between
containers — re-check `.env` and recreate.

## 5. Rollback

The split is purely a compose overlay; drop it to return to the monolith:

```bash
cd /opt/magister/deploy/compose
docker compose -f docker-compose.yml -f docker-compose.split10.yml down
docker compose -f docker-compose.yml up -d
# revert the Caddy per-container routes, then:
docker compose -f docker-compose.yml restart caddy
```

No data migration is involved either way — the schema and database are shared.
