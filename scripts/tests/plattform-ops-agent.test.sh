#!/usr/bin/env bash
# Der Host-Agent (scripts/plattform-ops-agent.sh) führt nur die bekannten
# Aufträge aus und reicht von der Auftragsdatei nichts weiter als ein geprüftes
# Kürzel.
#
# Ohne Docker und ohne Konsole: das Aufbau-Skript ist eine Attrappe, die nur
# ihre Argumente mitschreibt. Geprüft wird, dass „rotate-role“ und „attach“
# beim richtigen Befehl ankommen, ein manipuliertes Kürzel nirgends, und ein
# unbekannter Auftrag gar nichts auslöst.
set -euo pipefail

ECHT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/repo/scripts" "$T/ops/requests"
cp "$ECHT/scripts/plattform-ops-agent.sh" "$T/repo/scripts/"
cat > "$T/repo/scripts/plattform-aufbau.sh" <<X
#!/usr/bin/env bash
echo "\$*" >> "$T/aufrufe"
X
chmod +x "$T/repo/scripts/plattform-aufbau.sh"
# Keine Zustandserhebung im Test: eine frische health.json lässt sie aus.
echo '{}' > "$T/ops/health.json"

fehler=0
soll() {  # $1 = Bedingung (Befehl), $2 = Beschreibung
  if eval "$1"; then echo "  ok   $2"; else echo "  FEHL $2"; fehler=1; fi
}
auftrag() {  # $1 = Dateiname, $2 = JSON
  printf '%s\n' "$2" > "$T/ops/requests/$1.json"
}
lauf() {
  : > "$T/aufrufe"
  OPS_DIR="$T/ops" REPO="$T/repo" bash "$T/repo/scripts/plattform-ops-agent.sh"
}

auftrag a '{"id":"a","action":"rotate-role","slug":"schusef","requested_by":"op@vb.ch"}'
lauf
soll 'grep -qx "rollenpasswort-neu schusef" "$T/aufrufe"' "rotate-role ruft rollenpasswort-neu <kürzel>"
soll 'grep -q "\"action\":\"rotate-role\"" "$T/ops/status.json"' "Zustand nennt den Auftrag"
soll 'grep -q "\"state\":\"success\"" "$T/ops/status.json"' "Zustand ist erledigt"
soll 'grep -q "\"slug\":\"schusef\"" "$T/ops/status.json"' "Zustand nennt den Kunden"
soll '[ -z "$(ls -A "$T/ops/requests")" ]' "Auftrag ist abgearbeitet"

auftrag b '{"id":"b","action":"attach","slug":"gmp","requested_by":"op@vb.ch"}'
lauf
soll 'grep -qx "kunde-anbinden gmp" "$T/aufrufe"' "attach ruft kunde-anbinden <kürzel>"

auftrag c '{"id":"c","action":"rotate-role","slug":"x;touch /tmp/gehackt","requested_by":"op@vb.ch"}'
lauf
soll '[ ! -s "$T/aufrufe" ]' "manipuliertes Kürzel löst keinen Befehl aus"
soll 'grep -q "\"state\":\"error\"" "$T/ops/status.json"' "manipuliertes Kürzel endet als Fehler"

auftrag d '{"id":"d","action":"rm-rf","slug":"gmp","requested_by":"op@vb.ch"}'
lauf
soll '[ ! -s "$T/aufrufe" ]' "unbekannter Auftrag löst keinen Befehl aus"

test ! -e /tmp/gehackt
[ "$fehler" -eq 0 ] || exit 1
echo "plattform-ops-agent: bestanden"
