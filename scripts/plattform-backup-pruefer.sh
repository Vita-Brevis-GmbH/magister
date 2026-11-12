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
# Umgebung: REPO, PLATTFORM_ROOT, PLATTFORM_KONF (setzt die systemd-Einheit).
# Wo die Konsole liegt, wählt scripts/lib/konsole-pfad.sh — dieselbe Wahl wie
# in plattform-aufbau.sh.
set -euo pipefail

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ZIEL="${PLATTFORM_ROOT:-$REPO/plattform}"
KEY="$ZIEL/certs/backup-age.key"
# shellcheck source-path=SCRIPTDIR source=lib/konsole-pfad.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/konsole-pfad.sh"

[ -f "$KEY" ] || { echo "Privater Backup-Schlüssel $KEY fehlt." >&2; exit 2; }
konsole_waehlen "${PLATTFORM_KONF:-$ZIEL/plattform.conf}" \
  || { echo "$KONSOLE_FEHLER" >&2; exit 2; }

# Die Plattform-Überlagerung im eigenen Checkout hängt die Datenebene von
# dort ein (wie dc_konsole in plattform-aufbau.sh).
export MAGISTER_DIR="$REPO"
exec docker compose --project-directory "$KONSOLE_PFAD/deploy" \
  -f "$KONSOLE_PFAD/deploy/docker-compose.yml" \
  -f "$KONSOLE_PFAD/deploy/docker-compose.plattform.yml" \
  run --rm --no-deps -T \
  -v "$KEY:/run/backup-age.key:ro" \
  api python -m cockpit_api.cli.backup_worker --identity /run/backup-age.key
