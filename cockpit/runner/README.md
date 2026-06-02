# Cockpit Update-Runner

Drains `pending` update requests from the Cockpit API and executes them on the target Magister instances via SSH.

## Flow

1. `GET /api/update-requests/next` — atomic claim (state pending → in_progress), returns request + instance metadata
2. SSH to instance host, run `update.sh` with target version
3. Pre-snapshot via `pg_dump` (rollback safety)
4. `docker compose pull` + `docker compose up -d`
5. Smoke-test `/api/healthz` and verify version match
6. On success: `POST /complete`; on failure: `POST /fail` with error text and ⚠ leaves snapshot in place

## Configuration

Environment variables:

| Var | Description |
|---|---|
| `COCKPIT_URL` | Base URL of cockpit, e.g. `http://cockpit.internal:8001` |
| `COCKPIT_TOKEN` | Bootstrap token |
| `RUNNER_POLL_INTERVAL_S` | Default 30 |
| `RUNNER_SSH_USER` | Default `magister-ops` |
| `RUNNER_DRY_RUN` | If `1`, prints commands instead of running |

## Manual run

```bash
python -m cockpit_runner.main
```

## Ansible

See `deploy/ansible/roles/cockpit-update-runner/` for installing the runner as a systemd service.
