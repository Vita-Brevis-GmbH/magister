#!/usr/bin/env bash
# Die Rangfolge der Installations-Angaben in plattform-aufbau.sh.
#
# Warum es diesen Test gibt: zweimal hintereinander war nach einem Update
# die Konsole nicht mehr erreichbar, weil `up` ohne Optionen die Bindung auf
# die Vorgabe zurückgesetzt hat. Das ist kein Fehler, den man beim Lesen
# sieht — er entsteht aus dem Zusammenspiel von Vorgabewert, gespeichertem
# Wert und `setze_wert`. Also wird er gemessen.
#
# Der Test braucht weder Docker noch Netz: `PLATTFORM_NUR_KONFIG=1` lässt
# `up` nach dem Festschreiben der Angaben aufhören.
#
#   ./scripts/tests/plattform-konfig.test.sh

set -uo pipefail

SKRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/scripts/plattform-aufbau.sh"
ARBEIT="$(mktemp -d)"
trap 'rm -rf "$ARBEIT"' EXIT

GRUEN=0
ROT=0

lauf() {  # $1 = Befehl, Rest = Argumente -> Ausgabe auf stdout
  local befehl="$1"; shift
  env -u PLATTFORM_DOMAIN -u PLATTFORM_BIND -u PLATTFORM_ZUSATZNAME \
      PLATTFORM_ROOT="$ARBEIT" \
      PLATTFORM_NUR_KONFIG=1 \
      PLATTFORM_NICHT_FRAGEN=1 \
      "${UMGEBUNG[@]}" \
      bash "$SKRIPT" "$befehl" "$@" 2>&1
}

pruefe() {  # $1 = Beschreibung, $2 = erwartet, $3 = tatsächlich
  if [ "$2" = "$3" ]; then
    printf '\033[32m  ok  \033[0m%s\n' "$1"
    GRUEN=$((GRUEN + 1))
  else
    printf '\033[31m  !!  %s\033[0m\n      erwartet: %s\n      erhalten: %s\n' "$1" "$2" "$3"
    ROT=$((ROT + 1))
  fi
}

wert() {  # $1 = Schlüssel, $2 = Ausgabe
  printf '%s' "$2" | grep -oP "(?<=^$1=).*" | head -1
}

UMGEBUNG=()

printf '\n\033[1m1 · Erstinstallation ohne Angaben — Vorgaben, und sie werden gespeichert\033[0m\n'
A="$(lauf up)"
pruefe "Bindung ist die Vorgabe"        "127.0.0.1"                    "$(wert PLATTFORM_BIND "$A")"
pruefe "Konfiguration wurde angelegt"   "ja"                           "$([ -f "$ARBEIT/plattform.conf" ] && echo ja || echo nein)"

printf '\n\033[1m2 · Angaben auf der Kommandozeile — sie gelten und werden gespeichert\033[0m\n'
A="$(lauf up --bind 172.25.12.10 --zusatzname dev01-000-vb.int.vitabrevis.ch --domaene mgmt.example.ch)"
pruefe "Bindung übernommen"             "172.25.12.10"                 "$(wert PLATTFORM_BIND "$A")"
pruefe "Zweiter Name übernommen"        "dev01-000-vb.int.vitabrevis.ch" "$(wert PLATTFORM_ZUSATZNAME "$A")"
pruefe "Domäne übernommen"              "mgmt.example.ch"              "$(wert PLATTFORM_DOMAIN "$A")"
pruefe "in der Datei angekommen"        "PLATTFORM_BIND=172.25.12.10"  "$(grep '^PLATTFORM_BIND=' "$ARBEIT/plattform.conf")"

printf '\n\033[1m3 · Das Update: `up` OHNE Optionen darf nichts vergessen\033[0m\n'
# Der eigentliche Grund für diese Datei. Vorher stand hier 127.0.0.1.
A="$(lauf up)"
pruefe "Bindung bleibt"                 "172.25.12.10"                 "$(wert PLATTFORM_BIND "$A")"
pruefe "Zweiter Name bleibt"            "dev01-000-vb.int.vitabrevis.ch" "$(wert PLATTFORM_ZUSATZNAME "$A")"
pruefe "Domäne bleibt"                  "mgmt.example.ch"              "$(wert PLATTFORM_DOMAIN "$A")"
pruefe "Konsolen-URL folgt der Domäne"  "https://konsole.mgmt.example.ch:4444" "$(wert KONSOLE_URL "$A")"

printf '\n\033[1m4 · Auch die lesenden Befehle sehen die Angaben\033[0m\n'
A="$(lauf konfig)"
pruefe "konfig zeigt die Bindung"       "172.25.12.10"                 "$(wert PLATTFORM_BIND "$A")"
pruefe "konfig speichert nicht um"      "PLATTFORM_BIND=172.25.12.10"  "$(grep '^PLATTFORM_BIND=' "$ARBEIT/plattform.conf")"
A="$(lauf konfig --bind 10.9.9.9)"
pruefe "konfig --bind gilt nur jetzt"   "10.9.9.9"                     "$(wert PLATTFORM_BIND "$A")"
pruefe "…und schreibt nichts fort"      "PLATTFORM_BIND=172.25.12.10"  "$(grep '^PLATTFORM_BIND=' "$ARBEIT/plattform.conf")"

printf '\n\033[1m5 · Umgebungsvariable schlägt die Datei, Option schlägt die Umgebung\033[0m\n'
UMGEBUNG=(PLATTFORM_BIND=10.0.0.5)
A="$(lauf konfig)"
pruefe "Umgebung gilt"                  "10.0.0.5"                     "$(wert PLATTFORM_BIND "$A")"
A="$(lauf konfig --bind 10.0.0.9)"
pruefe "Option schlägt Umgebung"        "10.0.0.9"                     "$(wert PLATTFORM_BIND "$A")"
UMGEBUNG=()

printf '\n\033[1m6 · Ein ausdrücklich leerer zweiter Name bleibt leer\033[0m\n'
A="$(lauf up --zusatzname "")"
pruefe "leer übernommen"                ""                             "$(wert PLATTFORM_ZUSATZNAME "$A")"
A="$(lauf up)"
pruefe "und bleibt nach dem Update leer" ""                            "$(wert PLATTFORM_ZUSATZNAME "$A")"
pruefe "Bindung dabei unangetastet"     "172.25.12.10"                 "$(wert PLATTFORM_BIND "$A")"

printf '\n\033[1m7 · 0.0.0.0 wird abgewiesen, egal woher es kommt\033[0m\n'
A="$(lauf konfig --bind 0.0.0.0)"
pruefe "Option 0.0.0.0"                 "ja"                           "$(printf '%s' "$A" | grep -q 'nicht zulässig' && echo ja || echo nein)"
UMGEBUNG=(PLATTFORM_BIND=0.0.0.0)
A="$(lauf konfig)"
pruefe "Umgebung 0.0.0.0"               "ja"                           "$(printf '%s' "$A" | grep -q 'nicht zulässig' && echo ja || echo nein)"
UMGEBUNG=()

printf '\n\033[1m8 · Die Konfigurationsdatei wird gelesen, nicht ausgeführt\033[0m\n'
cat >> "$ARBEIT/plattform.conf" <<'BOESE'
PLATTFORM_BIND=$(touch /tmp/plattform-konfig-test-ausgefuehrt)
BOESE
rm -f /tmp/plattform-konfig-test-ausgefuehrt
A="$(lauf konfig)"
pruefe "kein Befehl ausgeführt"         "nein"                         "$([ -e /tmp/plattform-konfig-test-ausgefuehrt ] && echo ja || echo nein)"

printf '\n\033[1m9 · Gefragt wird genau einmal\033[0m\n'
# Braucht ein Pseudo-Terminal: ohne /dev/tty fragt das Skript gar nicht, und
# der Test prüfte dann nichts. `script` liefert eines. Gefüttert wird es mit
# leeren Zeilen — jede Frage nimmt damit ihren Vorschlag an. NICHT mit
# /dev/null: dann bekommt das Terminal nie ein Zeilenende, das Skript wartet
# auf eine Eingabe, die nicht kommt, und der Test hängt.
if command -v script >/dev/null; then
  FRAGE_ROOT="$ARBEIT/fragen"
  mkdir -p "$FRAGE_ROOT"
  mit_tty() {
    printf '\n\n\n' | env -u PLATTFORM_DOMAIN -u PLATTFORM_BIND -u PLATTFORM_ZUSATZNAME \
        PLATTFORM_ROOT="$FRAGE_ROOT" PLATTFORM_NUR_KONFIG=1 \
        script -qec "bash '$SKRIPT' up" /dev/null 2>&1
  }
  ERSTER="$(mit_tty)"
  pruefe "Erstinstallation fragt nach dem zweiten Namen" "ja" \
    "$(printf '%s' "$ERSTER" | grep -q 'Zweiter Name' && echo ja || echo nein)"
  ZWEITER="$(mit_tty)"
  pruefe "das Update fragt nicht mehr" "nein" \
    "$(printf '%s' "$ZWEITER" | grep -q 'Zweiter Name' && echo ja || echo nein)"
  pruefe "und hält denselben Wert" "$(wert PLATTFORM_ZUSATZNAME "$ERSTER")" \
    "$(wert PLATTFORM_ZUSATZNAME "$ZWEITER")"
  # Der Fall, der die Frage wiederkommen liess: zweiter Name absichtlich leer.
  LEER_ROOT="$ARBEIT/leer"; mkdir -p "$LEER_ROOT"
  printf 'PLATTFORM_DOMAIN=a.example\nPLATTFORM_BIND=10.0.0.7\nPLATTFORM_ZUSATZNAME=\n' \
    > "$LEER_ROOT/plattform.conf"
  A="$(printf '\n\n\n' | env -u PLATTFORM_DOMAIN -u PLATTFORM_BIND -u PLATTFORM_ZUSATZNAME \
        PLATTFORM_ROOT="$LEER_ROOT" PLATTFORM_NUR_KONFIG=1 \
        script -qec "bash '$SKRIPT' up" /dev/null 2>&1)"
  pruefe "leerer zweiter Name wird nicht neu gefragt" "nein" \
    "$(printf '%s' "$A" | grep -q 'Zweiter Name' && echo ja || echo nein)"
  pruefe "und bleibt leer" "PLATTFORM_ZUSATZNAME=" \
    "$(grep '^PLATTFORM_ZUSATZNAME=' "$LEER_ROOT/plattform.conf")"
else
  printf '\033[33m  --  script fehlt (util-linux) — Frage-Pfad nicht geprüft\033[0m\n'
fi

printf '\n'
if [ "$ROT" -eq 0 ]; then
  printf '\033[32m%d bestanden, 0 gescheitert\033[0m\n' "$GRUEN"
  exit 0
fi
printf '\033[31m%d bestanden, %d gescheitert\033[0m\n' "$GRUEN" "$ROT"
exit 1
