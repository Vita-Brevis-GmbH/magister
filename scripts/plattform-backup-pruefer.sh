#!/usr/bin/env bash
# Prüfer für Sicherungen auf einem Einzelhost (ADR-0024 D6).
#
# Startet einen kurzlebigen Container aus dem Abbild der Konsole und führt
# darin `cockpit_api.cli.backup_worker` aus: geschriebene Sicherungen prüfen,
# erfasste Wiederherstellungen einspielen, Ergebnisse melden.
#
# Der private Backup-Schlüssel wird NUR in diesen Container eingehängt, nicht
# in den laufenden Konsolen-Container (ADR-0016 D2). Auf einem echten
# Backup-Host läuft dasselbe Werkzeug dort, mit --console auf die Konsole.
#
# Umgebung: REPO, PLATTFORM_ROOT (setzt die systemd-Einheit).
set -euo pipefail

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ZIEL="${PLATTFORM_ROOT:-$REPO/plattform}"
KEY="$ZIEL/certs/backup-age.key"

[ -f "$KEY" ] || { echo "Privater Backup-Schlüssel $KEY fehlt." >&2; exit 2; }

exec docker compose --project-directory "$REPO/cockpit/deploy" \
  -f "$REPO/cockpit/deploy/docker-compose.yml" \
  -f "$REPO/cockpit/deploy/docker-compose.plattform.yml" \
  run --rm --no-deps -T \
  -v "$KEY:/run/backup-age.key:ro" \
  api python -m cockpit_api.cli.backup_worker --identity /run/backup-age.key
