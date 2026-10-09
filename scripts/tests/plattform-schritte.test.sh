#!/usr/bin/env bash
# „Nächste Schritte“ nach `plattform-aufbau.sh up`: nur, was noch offen ist.
#
# Ohne Docker und ohne Netz: die Funktionen werden aus dem Skript gelesen und
# gegen Attrappen ausgeführt (Namensauflösung, Operator-Abfrage, Kundenliste
# der Konsole). Geprüft wird, dass erledigte Schritte verschwinden, offene mit
# dem passenden Befehl erscheinen und `schritte` alles zeigt.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

# Der Abschnitt aus dem Skript, ohne den Rest (der würde Docker anfassen).
sed -n '/^# --- Nächste Schritte/,/^cmd_status() {/p' "$REPO/scripts/plattform-aufbau.sh" \
  | sed '$d' > "$T/schritte.sh"
grep -q '^naechste_schritte()' "$T/schritte.sh" \
  || { echo "naechste_schritte nicht im Skript gefunden"; exit 1; }

cat > "$T/harness.sh" <<'X'
say()  { printf '==> %s\n' "$*"; }
KONSOLE_HOST=konsole.dev.test; DOMAIN=dev.test; BIND=172.25.12.10; CERTS=/x/certs; ZUSATZNAME=
PAKETE="$PAKETE_DIR"
konsole_kunden() { printf 'gmp id ref role schema key active 42\n'; }
getent() { [ "${AUFGELOEST:-0}" = 1 ]; }
dc_konsole() { echo "${OPS:-0}"; }
source "$1"
naechste_schritte "${2:-}"
X

laeuft() {  # $1 Name, Rest: Umgebung — Ausgabe nach $T/out
  local name="$1"; shift
  env PAKETE_DIR="$T/pakete" "$@" bash "$T/harness.sh" "$T/schritte.sh" "${MODUS:-}" \
    > "$T/out" 2>&1 || { echo "FEHLER: $name brach ab"; cat "$T/out"; exit 1; }
}
enthaelt()     { grep -qF -- "$1" "$T/out" || { echo "FEHLER: '$1' fehlt"; cat "$T/out"; exit 1; }; }
enthaelt_nicht() { ! grep -qF -- "$1" "$T/out" || { echo "FEHLER: '$1' steht da"; cat "$T/out"; exit 1; }; }

mkdir -p "$T/pakete"

# 1) Alles offen: drei Schritte, mit den fehlenden Namen und dem Befehl.
laeuft "alles offen" AUFGELOEST=0 OPS=0
enthaelt "Nächste Schritte"
enthaelt "es fehlen: konsole.dev.test connect.dev.test gmp.dev.test"
enthaelt 'echo "172.25.12.10 konsole.dev.test connect.dev.test gmp.dev.test" >> /etc/hosts'
enthaelt "operator --upn"
enthaelt "agentenpakete.sh holen"

# 2) Alles erledigt: eine Zeile, keine Liste.
touch "$T/pakete/magister-connector-0.2.190-x64-abc12345.msi"
laeuft "alles erledigt" AUFGELOEST=1 OPS=1
enthaelt "Einrichtung vollständig"
enthaelt_nicht "Nächste Schritte"

# 3) Nur der Operator fehlt: genau dieser Schritt, als Nummer 1.
laeuft "nur Operator" AUFGELOEST=1 OPS=0
enthaelt "1. Ersten Operator anlegen"
enthaelt_nicht "Namen auflösbar"
enthaelt_nicht "Agenten-MSI"

# 4) Nicht feststellbar zählt als offen (Konsole aus).
laeuft "Operator unbekannt" AUFGELOEST=1 OPS=
enthaelt "Ersten Operator anlegen"

# 5) `schritte`: alles, auch Erledigtes, und der Prüfhinweis.
MODUS=alle laeuft "alle zeigen" AUFGELOEST=1 OPS=1
enthaelt "Namen auflösbar"
enthaelt "Ersten Operator anlegen"
enthaelt "Agenten-MSI bereitstellen"
enthaelt "plattform-auf-einem-host.md §5"

# 6) Kein .deb mehr in den Hinweisen.
enthaelt_nicht ".deb"

# 7) Produktion: DNS statt /etc/hosts — öffentlich der Platzhalter, intern die Konsole.
laeuft "prod: Namen fehlen" AUFGELOEST=0 OPS=1 ART=prod
enthaelt "*.dev.test  → öffentliche IP der Firewall"
enthaelt "konsole.dev.test  → 172.25.12.10"
enthaelt "prod-installation.md §2"
enthaelt_nicht "/etc/hosts"

echo "plattform-schritte: alle Fälle bestanden"
