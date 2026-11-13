#!/usr/bin/env bash
# bootstrap-cockpit-token.sh — gehört der Konsole und liegt seit 2026-11 in
# vitabrevis-cockpit (scripts/bootstrap-cockpit-token.sh, ADR 0009 dort).
# Dieses Skript reicht nur weiter, an den Checkout der Konsole, den auch
# plattform-aufbau.sh nimmt (scripts/lib/konsole-pfad.sh).
#
#   ./scripts/bootstrap-cockpit-token.sh --description "ops-team" [--ttl-days 90]
#
# Das Bootstrap-Token kommt dort aus der .env der Konsole, nicht aus der
# Kommandozeile. Hilfe: ./scripts/bootstrap-cockpit-token.sh --help
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source-path=SCRIPTDIR source=lib/konsole-pfad.sh
source "$REPO/scripts/lib/konsole-pfad.sh"

konsole_waehlen "${PLATTFORM_KONF:-${PLATTFORM_ROOT:-$REPO/plattform}/plattform.conf}" \
  || { echo "$KONSOLE_FEHLER" >&2; exit 1; }
ziel="$KONSOLE_PFAD/scripts/bootstrap-cockpit-token.sh"
[ -f "$ziel" ] \
  || { echo "Die Konsole in $KONSOLE_PFAD ist zu alt: $ziel fehlt (git -C $KONSOLE_PFAD pull)." >&2; exit 1; }
exec bash "$ziel" "$@"
