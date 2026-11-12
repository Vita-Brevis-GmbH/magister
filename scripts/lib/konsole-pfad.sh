# shellcheck shell=bash
# shellcheck disable=SC2034  # KONSOLE_* sind das Ergebnis für den Aufrufer
# Wo die Konsole (Control Plane) liegt — EIN Ort für alle Skripte.
#
# Die Konsole lebt in einem eigenen Repository (vitabrevis-cockpit), auf den
# Hosts geklont nach /opt/cockpit/src. Der Ordner `cockpit/` ist aus Magister
# entfernt; auf einem Host, der noch nicht umgezogen ist, liegen dort nur
# noch die unversionierten Reste (.env, certs/) — die Quelle für
# `plattform-aufbau.sh konsole-umziehen`, aber kein Ort, aus dem die Konsole
# läuft. Jedes Skript, das die Konsole anfasst, muss denselben Checkout
# wählen: sonst baut `up` die Oberfläche im einen, und Caddy hängt den
# anderen ein — oder der Prüfer liest eine `.env`, die nicht mehr gilt.
#
# Rangfolge, von stark nach schwach:
#   1. ausdrückliche Angabe: Umgebung PLATTFORM_KONSOLE (in
#      plattform-aufbau.sh dazu die Option --konsole, stärker als die Umgebung)
#   2. gespeicherter Wert PLATTFORM_KONSOLE in der Installations-Konfiguration
#      von plattform-aufbau.sh ($KONF, Vorgabe plattform/plattform.conf)
#   3. nur Entwicklerrechner: vitabrevis-cockpit neben dem Magister-Repo
#   4. /opt/cockpit/src — auf einem Host, für den nichts gespeichert ist
#
# Eine Angabe aus 1 oder 2 wird nie still durch einen Rückfall ersetzt: zeigt
# sie ins Leere, ist das ein Fehler. Sonst liefe die Konsole nach einem
# Tippfehler unbemerkt aus einem anderen Checkout — mit einer anderen
# Datenbank.
#
# Eingebunden mit `source`; erwartet REPO (Wurzel des Magister-Repos). Ruft
# kein `exit` und setzt keine Shell-Optionen — abbrechen tut der Aufrufer
# mit seinem eigenen `die`:
#
#   konsole_waehlen "$KONF" || die "$KONSOLE_FEHLER"
#   docker compose --project-directory "$KONSOLE_PFAD/deploy" …
#
# Ergebnis in KONSOLE_PFAD (absolut), KONSOLE_HERKUNFT (woher die Wahl kam)
# und, wenn ungültig, KONSOLE_FEHLER (ein Satz für `die`).

# Der Klon auf den Hosts. Eine Variable nur, damit die Tests ihn umlenken
# können, ohne /opt anzufassen.
KONSOLE_KLON="/opt/cockpit/src"
KONSOLE_REPO_URL="https://github.com/Vita-Brevis-GmbH/vitabrevis-cockpit.git"

KONSOLE_PFAD=""
KONSOLE_HERKUNFT=""
KONSOLE_FEHLER=""

#: Absoluter Pfad ohne Schrägstrich am Ende — sofern es das Verzeichnis gibt.
#: Ein relativer Pfad gilt vom Arbeitsverzeichnis aus, wie auf der Kommandozeile.
konsole_absolut() {  # $1 = Pfad
  local pfad="${1:-}"
  [ -n "$pfad" ] || return 0
  if [ -d "$pfad" ]; then
    (CDPATH='' cd -- "$pfad" >/dev/null 2>&1 && pwd)
  else
    printf '%s' "${pfad%/}"
  fi
}

#: Der gespeicherte Pfad aus der Installations-Konfiguration, leer = keiner.
#: Gelesen, nicht ausgeführt — wie konf_laden in plattform-aufbau.sh, und wie
#: dort gilt die erste Zeile.
konsole_aus_konf() {  # $1 = Konfigurationsdatei (leer = keine)
  [ -n "${1:-}" ] && [ -f "$1" ] || return 0
  grep -E '^PLATTFORM_KONSOLE=' "$1" 2>/dev/null | head -1 | cut -d= -f2-
}

#: Die Auswahl nach der Rangfolge oben, für Skripte ohne eigene Option:
#: Umgebung, dann die Konfigurationsdatei, dann die Rückfälle.
konsole_waehlen() {  # $1 = Konfigurationsdatei (leer = keine), $2 = "dev" auf Entwicklerrechnern
  local angabe="${PLATTFORM_KONSOLE:-}" herkunft="Umgebung PLATTFORM_KONSOLE"
  if [ -z "$angabe" ]; then
    angabe="$(konsole_aus_konf "${1:-}")"
    herkunft="gespeichert in ${1:-}"
  fi
  konsole_aufloesen "$angabe" "$herkunft" "${2:-}"
}

#: Kern der Auswahl. Eine Angabe gilt, wenn es sie gibt — sonst die Rückfälle.
konsole_aufloesen() {  # $1 = Angabe (leer = keine), $2 = woher sie kommt, $3 = "dev" -> 0 = gültig
  local angabe="${1:-}" dev="${3:-}" daneben
  KONSOLE_PFAD=""; KONSOLE_HERKUNFT=""; KONSOLE_FEHLER=""
  daneben="$(dirname "$REPO")/vitabrevis-cockpit"
  if [ -n "$angabe" ]; then
    KONSOLE_PFAD="$(konsole_absolut "$angabe")"
    KONSOLE_HERKUNFT="${2:-Angabe}"
  elif [ "$dev" = "dev" ] && [ -f "$daneben/deploy/docker-compose.yml" ]; then
    KONSOLE_PFAD="$(konsole_absolut "$daneben")"
    KONSOLE_HERKUNFT="neben dem Magister-Repo"
  else
    KONSOLE_PFAD="$KONSOLE_KLON"
    KONSOLE_HERKUNFT="Vorgabe"
  fi
  [ -f "$KONSOLE_PFAD/deploy/docker-compose.yml" ] && return 0

  if [ -n "$angabe" ]; then
    KONSOLE_FEHLER="Konsole nicht gefunden: $KONSOLE_PFAD/deploy/docker-compose.yml fehlt ($KONSOLE_HERKUNFT). Den Checkout von vitabrevis-cockpit angeben: PLATTFORM_KONSOLE=<pfad> bzw. plattform-aufbau.sh up --konsole <pfad>."
  else
    local gesucht="$KONSOLE_KLON"
    [ "$dev" = "dev" ] && gesucht="$daneben und $KONSOLE_KLON"
    KONSOLE_FEHLER="Keine Konsole gefunden — deploy/docker-compose.yml fehlt in $gesucht. Klonen: git clone $KONSOLE_REPO_URL $KONSOLE_KLON — oder den Ort angeben: PLATTFORM_KONSOLE=<pfad> bzw. plattform-aufbau.sh up --konsole <pfad>."
    # Ein Host, der noch nicht umgezogen ist: nach dem Klonen kommt der
    # Umzug, nicht ein `up` — das bräche ohnehin mit demselben Hinweis ab.
    if [ -f "$REPO/cockpit/deploy/.env" ]; then
      KONSOLE_FEHLER="$KONSOLE_FEHLER Bisher lief sie aus $REPO/cockpit (dort liegt noch ihre .env): nach dem Klonen zuerst umziehen — scripts/plattform-aufbau.sh konsole-umziehen $KONSOLE_KLON."
    fi
  fi
  return 1
}

#: Hat die Compose-Datei ein festes `name:`? Nur dann heissen Projekt und
#: Volumes unabhängig vom Ordner — im eigenen Repo `cockpit`.
konsole_hat_namen() {  # $1 = Konsolen-Pfad
  grep -qE '^name:[[:space:]]*[^[:space:]#]' "$1/deploy/docker-compose.yml" 2>/dev/null
}

#: Der Projektname, wie Compose ihn bildet: `name:` in der Datei, sonst der
#: Name des Projektordners. Daran hängen die Namen der Volumes —
#: `cockpit_cockpit-pg` im eigenen Repo, `deploy_cockpit-pg` aus `cockpit/` im
#: Magister-Repo vor dem Auszug. Für den alten Ort, wo die Compose-Datei
#: inzwischen fehlt, ergibt das weiterhin `deploy`.
konsole_projekt() {  # $1 = Konsolen-Pfad
  local name=""
  if konsole_hat_namen "$1"; then
    name="$(sed -n 's/^name:[[:space:]]*//p' "$1/deploy/docker-compose.yml" | head -1)"
    name="${name%%#*}"
    name="${name//[[:space:]\"\']/}"
  fi
  [ -n "$name" ] || name="$(basename "$1/deploy")"
  printf '%s' "$name" | tr '[:upper:]' '[:lower:]'
}
