#!/usr/bin/env bash
# Host-Agent für Neustart und Update der Plattform (ADR-0024 D5).
#
# Die Konsole legt Aufträge als Datei in $OPS_DIR/requests/ ab; dieses Skript
# — vom systemd-Timer aus `plattform-aufbau.sh ops-agent` aufgerufen — führt
# sie aus und schreibt das Ergebnis nach $OPS_DIR/status.json und last.log.
#
# Es kennt genau zwei Aufträge und liest aus der Datei nichts anderes als den
# Namen des Auftrags. Eine übernommene Konsole kann damit einen Neustart oder
# ein Update bestellen, aber keinen beliebigen Befehl auf dem Host ausführen.
#
#   restart  beide Stacks neu starten (ohne Neubau)
#   update   git pull --ff-only, dann plattform-aufbau.sh update
#
# Umgebung: OPS_DIR (Pflicht), REPO (Vorgabe: Verzeichnis über diesem Skript).
set -uo pipefail

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
OPS_DIR="${OPS_DIR:?OPS_DIR fehlt}"
REQ_DIR="$OPS_DIR/requests"
STATUS="$OPS_DIR/status.json"
LOGFILE="$OPS_DIR/last.log"
AUFBAU="$REPO/scripts/plattform-aufbau.sh"

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
git_sha() { git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo "unbekannt"; }
json_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -d '\000-\010\013\014\016-\037' \
    | awk 'BEGIN{ORS="\\n"}{print}'
}
feld() {  # $1 = Datei, $2 = Feldname; nur [A-Za-z0-9_.@:-] wird übernommen
  sed -n "s/.*\"$2\"[[:space:]]*:[[:space:]]*\"\([A-Za-z0-9_.@:+-]*\)\".*/\1/p" "$1" | head -1
}
write_status() {  # action state message started finished requested_by
  local tmp="$STATUS.tmp"
  printf '{"action":"%s","state":"%s","message":"%s","git_sha":"%s","started_at":"%s","finished_at":"%s","requested_by":"%s"}\n' \
    "$1" "$2" "$(json_escape "$3")" "$(git_sha)" "$4" "$5" "$6" >"$tmp"
  mv -f "$tmp" "$STATUS"
}

run_action() {
  case "$1" in
    restart) "$AUFBAU" restart ;;
    update)  git -C "$REPO" pull --ff-only && "$AUFBAU" update ;;
    *)       echo "unbekannter Auftrag: $1"; return 2 ;;
  esac
}

[ -d "$REQ_DIR" ] || exit 0
# Ein Lauf zur Zeit: ein Update, das länger dauert als das Timer-Intervall,
# darf nicht von einem zweiten überholt werden.
exec 9>"$OPS_DIR/.lock"
flock -n 9 || exit 0

for req in $(ls -1tr "$REQ_DIR"/*.json 2>/dev/null); do
  action="$(feld "$req" action)"
  who="$(feld "$req" requested_by)"
  started="$(now)"
  case "$action" in
    restart|update) : ;;
    *)
      write_status "${action:-ungültig}" "error" "unbekannter oder unlesbarer Auftrag" "$started" "$(now)" "$who"
      rm -f "$req"; continue ;;
  esac
  : >"$LOGFILE"
  write_status "$action" "running" "" "$started" "" "$who"
  # Den Auftrag VOR dem Lauf entfernen: ein Update startet die Konsole neu,
  # und ein Auftrag, der danach noch daläge, liefe beim nächsten Takt erneut.
  rm -f "$req"
  run_action "$action" >>"$LOGFILE" 2>&1
  code=$?
  tail_out="$(tail -c 2000 "$LOGFILE" 2>/dev/null)"
  if [ "$code" -eq 0 ]; then
    write_status "$action" "success" "$tail_out" "$started" "$(now)" "$who"
  else
    write_status "$action" "error" "$tail_out" "$started" "$(now)" "$who"
  fi
done
