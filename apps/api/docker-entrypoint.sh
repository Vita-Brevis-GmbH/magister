#!/usr/bin/env bash
# Apply pending Alembic migrations, then exec the actual server command.
# Set MAGISTER_SKIP_MIGRATIONS=1 to skip (e.g. when running a one-shot CLI).
set -euo pipefail

if [[ "${MAGISTER_SKIP_MIGRATIONS:-0}" != "1" ]]; then
  echo "[entrypoint] running alembic upgrade head"
  alembic upgrade head
fi

echo "[entrypoint] exec: $*"
exec "$@"
