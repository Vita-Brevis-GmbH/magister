#!/usr/bin/env bash
# Wo die Konsole liegt (scripts/lib/konsole-pfad.sh) — und dass
# plattform-aufbau.sh sie umzieht, ohne etwas zu verlieren.
#
# Warum es diesen Test gibt: die Konsole zieht aus cockpit/ in einen eigenen
# Checkout (vitabrevis-cockpit). Wählt ein Skript einen anderen Ort als das
# nächste, baut `up` die Oberfläche im einen Checkout und Caddy hängt den
# anderen ein — und startet die Konsole im neuen Checkout ohne ihre
# Datenbank, kennt die Datenebene danach keinen Kunden mehr.
#
# Ohne Docker und ohne Netz: die Pfade sind Verzeichnisse unter einem
# Arbeitsordner, plattform-aufbau.sh läuft als Kopie in einem nachgebauten
# Repo, und `docker` ist eine Attrappe, die jeden Aufruf mitschreibt. Volumes
# sind darin Dateien mit Projekt und Inhalt.
#
#   ./scripts/tests/konsole-pfad.test.sh

set -uo pipefail
# Was die Umgebung des Aufrufers sagt, gilt hier nicht.
unset PLATTFORM_KONSOLE PLATTFORM_KONF

ECHT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIB="$ECHT/scripts/lib/konsole-pfad.sh"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

GRUEN=0
ROT=0

pruefe() {  # $1 = Beschreibung, $2 = erwartet, $3 = tatsächlich
  if [ "$2" = "$3" ]; then
    printf '\033[32m  ok  \033[0m%s\n' "$1"
    GRUEN=$((GRUEN + 1))
  else
    printf '\033[31m  !!  %s\033[0m\n      erwartet: %s\n      erhalten: %s\n' "$1" "$2" "$3"
    ROT=$((ROT + 1))
  fi
}

ja_wenn() { if "$@"; then echo ja; else echo nein; fi; }

konsole() {  # $1 = Pfad, $2 = Zeile mit name: (leer = keine) — ein Checkout
  mkdir -p "$1/deploy"
  { [ -n "${2:-}" ] && printf '%s\n' "$2"; printf 'services: {}\n'; } > "$1/deploy/docker-compose.yml"
  printf 'services: {}\n' > "$1/deploy/docker-compose.plattform.yml"
}

# --- Arbeitsplatz: Magister, ein Checkout daneben, der Klon unter „/opt" ----
WS="$T/ws"
MAG="$WS/magister"
konsole "$MAG/cockpit"
konsole "$WS/vitabrevis-cockpit" "name: cockpit"
konsole "$T/opt/cockpit/src" "name: cockpit"
konsole "$T/eigen" "name: cockpit"
konsole "$T/gespeichert" "name: cockpit"
mkdir -p "$T/conf"
printf 'PLATTFORM_DOMAIN=example.ch\nPLATTFORM_KONSOLE=%s\n' "$T/gespeichert" > "$T/conf/plattform.conf"
: > "$T/conf/leer.conf"

waehle() {  # $1 = Konfigurationsdatei, $2 = dev -> "Pfad|Herkunft" oder "FEHLER|Grund"
  (
    REPO="$MAG"
    # shellcheck source-path=SCRIPTDIR source=../lib/konsole-pfad.sh
    source "$LIB"
    KONSOLE_KLON="$T/opt/cockpit/src"
    if konsole_waehlen "${1:-}" "${2:-}"; then
      printf '%s|%s' "$KONSOLE_PFAD" "$KONSOLE_HERKUNFT"
    else
      printf 'FEHLER|%s' "$KONSOLE_FEHLER"
    fi
  )
}
pfad() { printf '%s' "${1%%|*}"; }

printf '\n\033[1m1 · Rangfolge: Umgebung → gespeichert → cockpit/ → (dev: daneben) → /opt/cockpit/src\033[0m\n'
A="$(PLATTFORM_KONSOLE="$T/eigen" waehle "$T/conf/plattform.conf")"
pruefe "Umgebung schlägt die Konfiguration"    "$T/eigen"              "$(pfad "$A")"
A="$(waehle "$T/conf/plattform.conf")"
pruefe "gespeichert schlägt den Rückfall"      "$T/gespeichert"        "$(pfad "$A")"
pruefe "…und sagt, woher"                      "gespeichert in $T/conf/plattform.conf" "${A#*|}"
A="$(waehle "$T/conf/leer.conf")"
pruefe "ohne Angabe: cockpit/ im Magister-Repo" "$MAG/cockpit"         "$(pfad "$A")"
A="$(waehle "")"
pruefe "ohne Konfigurationsdatei ebenso"       "$MAG/cockpit"          "$(pfad "$A")"
A="$(waehle "" dev)"
pruefe "Entwicklerrechner: cockpit/ geht vor"  "$MAG/cockpit"          "$(pfad "$A")"

# Der spätere Zustand: cockpit/ ist aus Magister entfernt.
mv "$MAG/cockpit" "$T/cockpit-weg"
ohne() { waehle "" "${1:-}"; }
pruefe "ohne cockpit/: der Klon unter /opt"    "$T/opt/cockpit/src"    "$(pfad "$(ohne)")"
pruefe "Entwicklerrechner: der Checkout daneben" "$WS/vitabrevis-cockpit" "$(pfad "$(ohne dev)")"
mv "$T/opt/cockpit/src" "$T/klon-weg"
A="$(ohne)"
pruefe "nichts gefunden: Fehler statt Raten"   "FEHLER"                "$(pfad "$A")"
pruefe "…mit dem Weg zum Klon"                 "ja" "$(ja_wenn grep -q 'git clone .*vitabrevis-cockpit' <<<"$A")"
mv "$T/klon-weg" "$T/opt/cockpit/src"
mv "$T/cockpit-weg" "$MAG/cockpit"

printf '\n\033[1m2 · Eine Angabe, die ins Leere zeigt, ist ein Fehler — kein stiller Rückfall\033[0m\n'
A="$(PLATTFORM_KONSOLE="$T/vertippt" waehle "")"
pruefe "Umgebung ins Leere"                    "FEHLER"                "$(pfad "$A")"
pruefe "…nennt die fehlende Datei"             "ja" "$(ja_wenn grep -qF "$T/vertippt/deploy/docker-compose.yml" <<<"$A")"
printf 'PLATTFORM_KONSOLE=%s\n' "$T/vertippt" > "$T/conf/vertippt.conf"
A="$(waehle "$T/conf/vertippt.conf")"
pruefe "gespeichert ins Leere"                 "FEHLER"                "$(pfad "$A")"
mkdir -p "$T/ohne-compose/deploy"
A="$(PLATTFORM_KONSOLE="$T/ohne-compose" waehle "")"
pruefe "Ordner ohne deploy/docker-compose.yml" "FEHLER"                "$(pfad "$A")"
A="$(cd "$T" && PLATTFORM_KONSOLE="./eigen/" waehle "")"
pruefe "relativer Pfad wird absolut"           "$T/eigen"              "$(pfad "$A")"

printf '\n\033[1m3 · Projektname und Konfigurationsdatei\033[0m\n'
projekt() {
  # shellcheck source-path=SCRIPTDIR source=../lib/konsole-pfad.sh
  ( REPO="$MAG"; source "$LIB"; konsole_projekt "$1" )
}
pruefe "ohne name: heisst das Projekt deploy"  "deploy"                "$(projekt "$MAG/cockpit")"
pruefe "name: cockpit"                         "cockpit"               "$(projekt "$T/eigen")"
konsole "$T/zitiert" "name: \"Cockpit\"  # fest"
pruefe "Anführungszeichen, Kommentar, Grossbuchstaben" "cockpit"       "$(projekt "$T/zitiert")"
# shellcheck disable=SC2016  # wörtlich: genau das darf nie ausgeführt werden
printf 'PLATTFORM_KONSOLE=$(touch %s/ausgefuehrt)\n' "$T" > "$T/conf/boese.conf"
# shellcheck source-path=SCRIPTDIR source=../lib/konsole-pfad.sh
( REPO="$MAG"; source "$LIB"; konsole_aus_konf "$T/conf/boese.conf" >/dev/null )
pruefe "Konfiguration gelesen, nicht ausgeführt" "nein" "$(ja_wenn test -e "$T/ausgefuehrt")"

# --- plattform-aufbau.sh in einem nachgebauten Repo --------------------------
REPO_T="$T/repo"
mkdir -p "$REPO_T/scripts/lib"
cp "$ECHT/scripts/plattform-aufbau.sh" "$REPO_T/scripts/"
cp "$LIB" "$REPO_T/scripts/lib/"
konsole "$REPO_T/cockpit"
ALT="$REPO_T/cockpit/deploy"
printf 'COCKPIT_BOOTSTRAP_TOKEN=alt\n' > "$ALT/.env"; chmod 600 "$ALT/.env"
mkdir -p "$ALT/certs"
printf 'alt\n' > "$ALT/certs/console.pem"; printf 'alt\n' > "$ALT/certs/root.pem"

ROOT="$T/plattform"
KONF="$ROOT/plattform.conf"
mkdir -p "$ROOT" "$T/bin" "$T/dz/vol"

lauf() {  # $1 = Befehl, Rest = Argumente -> Ausgabe (stdout + stderr)
  env -u PLATTFORM_DOMAIN -u PLATTFORM_BIND -u PLATTFORM_ZUSATZNAME \
      -u PLATTFORM_ART -u PLATTFORM_TLS -u PLATTFORM_ACME_MAIL -u PLATTFORM_WAF \
      -u PLATTFORM_KONSOLE -u PLATTFORM_KONF \
      PATH="$T/bin:$PATH" DZ="$T/dz" \
      PLATTFORM_ROOT="$ROOT" PLATTFORM_NUR_KONFIG=1 PLATTFORM_NICHT_FRAGEN=1 \
      "${UMGEBUNG[@]}" \
      bash "$REPO_T/scripts/plattform-aufbau.sh" "$@" 2>&1
}
wert() {  # $1 = Schlüssel, $2 = Ausgabe
  printf '%s' "$2" | grep -oP "(?<=^$1=).*" | head -1
}
UMGEBUNG=()

# --- Docker-Attrappe ----------------------------------------------------------
# Ein Volume ist die Datei $DZ/vol/<name> mit „<projekt> <inhalt>" (inhalt:
# leer oder postgres). Jeder Aufruf landet mit MAGISTER_DIR in $DZ/aufrufe.
cat > "$T/bin/docker" <<'X'
#!/usr/bin/env bash
echo "MAGISTER_DIR=${MAGISTER_DIR:-} docker $*" >> "$DZ/aufrufe"
case "${1:-} ${2:-}" in
  "volume inspect") [ -f "$DZ/vol/$3" ]; exit $? ;;
  "volume ls")
    for f in "$DZ"/vol/*; do
      [ -f "$f" ] && printf '%s %s\n' "${f##*/}" "$(cut -d' ' -f1 "$f")"
    done
    exit 0 ;;
  "run --rm")
    q=""; z=""; v=""
    for a in "$@"; do
      case "$a" in
        *:/quelle:ro) q="${a%%:/quelle:ro}" ;;
        *:/ziel) z="${a%%:/ziel}" ;;
        *:/v:ro) v="${a%%:/v:ro}" ;;
      esac
    done
    if [ -n "$q" ] && [ -n "$z" ]; then
      printf '%s %s\n' "$(cut -d' ' -f1 "$DZ/vol/$z")" "$(cut -d' ' -f2 "$DZ/vol/$q")" > "$DZ/vol/$z"
    elif [ -n "$v" ]; then
      cut -d' ' -f2 "$DZ/vol/$v"
    fi
    exit 0 ;;
  "ps -q") exit 0 ;;   # kein laufender Container hält ein Volume
esac
case "$*" in
  *"up --no-start postgres"*)
    [ -f "$DZ/vol/cockpit_cockpit-pg" ] || echo "cockpit leer" > "$DZ/vol/cockpit_cockpit-pg" ;;
esac
exit 0
X
chmod +x "$T/bin/docker"
aufrufe() { cat "$T/dz/aufrufe" 2>/dev/null; }
neu_aufrufe() { : > "$T/dz/aufrufe"; }

printf '\n\033[1m4 · plattform-aufbau.sh: bestehende Installation läuft weiter aus cockpit/\033[0m\n'
A="$(lauf konfig)"
pruefe "ohne Angabe: cockpit/ im Repo"         "$REPO_T/cockpit"       "$(wert KONSOLE_PFAD "$A")"
pruefe "…Projekt wie bisher"                   "deploy"                "$(wert KONSOLE_PROJEKT "$A")"

printf '\n\033[1m5 · --konsole wird bei up gespeichert, und ein Update vergisst es nicht\033[0m\n'
konsole "$T/neu" "name: cockpit"
A="$(lauf up --konsole "$T/neu" --bind 10.0.0.5)"
pruefe "Option gilt"                           "$T/neu"                "$(wert KONSOLE_PFAD "$A")"
pruefe "…und steht in der Konfiguration"       "PLATTFORM_KONSOLE=$T/neu" "$(grep '^PLATTFORM_KONSOLE=' "$KONF")"
A="$(lauf up)"
pruefe "up ohne Optionen behält den Ort"       "$T/neu"                "$(wert KONSOLE_PFAD "$A")"
pruefe "…und die übrigen Angaben"              "10.0.0.5"              "$(wert PLATTFORM_BIND "$A")"
A="$(lauf konfig --konsole "$T/eigen")"
pruefe "konfig --konsole gilt nur jetzt"       "$T/eigen"              "$(wert KONSOLE_PFAD "$A")"
pruefe "…und schreibt nichts fort"             "PLATTFORM_KONSOLE=$T/neu" "$(grep '^PLATTFORM_KONSOLE=' "$KONF")"
UMGEBUNG=(PLATTFORM_KONSOLE="$T/eigen")
A="$(lauf konfig)"
pruefe "Umgebung schlägt die Datei"            "$T/eigen"              "$(wert KONSOLE_PFAD "$A")"
A="$(lauf konfig --konsole "$T/gespeichert")"
pruefe "Option schlägt die Umgebung"           "$T/gespeichert"        "$(wert KONSOLE_PFAD "$A")"
UMGEBUNG=()
A="$(cd "$T" && lauf up --konsole ./neu/)"
pruefe "relativer Pfad wird absolut gespeichert" "PLATTFORM_KONSOLE=$T/neu" "$(grep '^PLATTFORM_KONSOLE=' "$KONF")"
neu_aufrufe
A="$(lauf status --konsole "$T/vertippt")"
pruefe "Befehl mit Konsole bricht ab, wenn sie fehlt" "ja" \
  "$(ja_wenn grep -q "Konsole nicht gefunden: $T/vertippt/deploy/docker-compose.yml" <<<"$A")"
pruefe "…bevor Docker gefragt wird"            "nein" "$(ja_wenn test -s "$T/dz/aufrufe")"
A="$(lauf konfig --konsole "$T/vertippt")"
pruefe "konfig zeigt den Fehler, ohne abzubrechen" "ja" \
  "$(ja_wenn grep -q '^KONSOLE_URL=' <<<"$A")"
A="$(lauf up --konsole "")"
pruefe "--konsole \"\": zurück zur Automatik"    "$REPO_T/cockpit"       "$(wert KONSOLE_PFAD "$A")"
pruefe "…gespeichert als leer"                 "PLATTFORM_KONSOLE="    "$(grep '^PLATTFORM_KONSOLE=' "$KONF")"

printf '\n\033[1m6 · konsole-umziehen prüft sein Ziel, bevor es etwas anfasst\033[0m\n'
neu_aufrufe
A="$(lauf konsole-umziehen)"
pruefe "ohne Pfad: Abbruch"                    "ja" "$(ja_wenn grep -q 'Wohin?' <<<"$A")"
A="$(lauf konsole-umziehen "$T/vertippt")"
pruefe "Ziel ohne Compose-Datei: Abbruch"      "ja" "$(ja_wenn grep -q 'kein Checkout von vitabrevis-cockpit' <<<"$A")"
konsole "$T/ohne-namen"
A="$(lauf konsole-umziehen "$T/ohne-namen")"
pruefe "Ziel ohne festes name:: Abbruch"       "ja" "$(ja_wenn grep -q "kein festes 'name:'" <<<"$A")"
A="$(lauf konsole-umziehen "$REPO_T/cockpit")"
pruefe "Ziel ist der alte Ort: Abbruch"        "ja" "$(ja_wenn grep -q 'bisherige Ort' <<<"$A")"
pruefe "…und Docker wurde nie gefragt"         "nein" "$(ja_wenn test -s "$T/dz/aufrufe")"

printf '\n\033[1m7 · Eine bestehende Installation startet unverändert\033[0m\n'
echo "deploy postgres" > "$T/dz/vol/deploy_cockpit-pg"
neu_aufrufe
A="$(lauf restart)"
pruefe "restart aus cockpit/ läuft durch"      "ja" "$(ja_wenn grep -q "project-directory $REPO_T/cockpit/deploy .* restart" <(aufrufe))"
pruefe "…mit MAGISTER_DIR"                     "ja" "$(ja_wenn grep -q "^MAGISTER_DIR=$REPO_T docker compose --project-directory $REPO_T/cockpit/deploy" <(aufrufe))"

printf '\n\033[1m8 · Schutz: neuer Checkout, Daten noch im alten — kein Start\033[0m\n'
konsole "$T/schutz" "name: cockpit"
printf 'PLATTFORM_KONSOLE=%s\n' "$T/schutz" > "$KONF"
neu_aufrufe
A="$(lauf restart)"
pruefe ".env fehlt im neuen Checkout: Abbruch" "ja" "$(ja_wenn grep -q 'konsole-umziehen' <<<"$A")"
pruefe "…mit dem Grund"                        "ja" "$(ja_wenn grep -q 'Umgebung (.env' <<<"$A")"
printf 'COCKPIT_BOOTSTRAP_TOKEN=x\n' > "$T/schutz/deploy/.env"
A="$(lauf restart)"
pruefe "Volume fehlt, altes da: Abbruch"       "ja" "$(ja_wenn grep -q "alten Volume deploy_cockpit-pg" <<<"$A")"
pruefe "…mit dem Hinweis auf konsole-umziehen" "ja" "$(ja_wenn grep -q "konsole-umziehen $T/schutz" <<<"$A")"
pruefe "…und nichts neu gestartet"             "nein" "$(ja_wenn grep -q ' restart' <(aufrufe))"

printf '\n\033[1m9 · konsole-umziehen: anhalten, kopieren, merken — nichts löschen\033[0m\n'
printf 'PLATTFORM_DOMAIN=example.ch\nPLATTFORM_BIND=10.0.0.5\n' > "$KONF"
mkdir -p "$T/neu/deploy/certs"
printf 'neu\n' > "$T/neu/deploy/certs/console.pem"   # vorhanden: bleibt
neu_aufrufe
A="$(lauf konsole-umziehen "$T/neu")"
pruefe "läuft durch"                           "ja" "$(ja_wenn grep -q 'Die Konsole ist umgezogen' <<<"$A")"
pruefe "alter Stack: down, mit beiden Dateien" "ja" \
  "$(ja_wenn grep -q "project-directory $ALT -f $ALT/docker-compose.yml -f $ALT/docker-compose.plattform.yml down" <(aufrufe))"
pruefe "…ohne -v"                              "nein" "$(ja_wenn grep -qE ' down .*-v|--volumes' <(aufrufe))"
pruefe ".env übernommen"                       "COCKPIT_BOOTSTRAP_TOKEN=alt" "$(cat "$T/neu/deploy/.env")"
pruefe "…mit ihren Rechten"                    "600" "$(stat -c %a "$T/neu/deploy/.env")"
pruefe "fehlendes Zertifikat übernommen"       "alt" "$(cat "$T/neu/deploy/certs/root.pem")"
pruefe "vorhandenes nicht überschrieben"       "neu" "$(cat "$T/neu/deploy/certs/console.pem")"
pruefe "Ziel-Volume über Compose angelegt"     "ja" \
  "$(ja_wenn grep -q "^MAGISTER_DIR=$REPO_T docker compose --project-directory $T/neu/deploy .* up --no-start postgres" <(aufrufe))"
pruefe "Datenbank kopiert, Quelle nur lesend"  "ja" \
  "$(ja_wenn grep -q 'run --rm -v deploy_cockpit-pg:/quelle:ro -v cockpit_cockpit-pg:/ziel postgres:16 cp -a /quelle/. /ziel/' <(aufrufe))"
pruefe "…und im Ziel angekommen"               "cockpit postgres" "$(cat "$T/dz/vol/cockpit_cockpit-pg")"
pruefe "altes Volume bleibt"                   "deploy postgres" "$(cat "$T/dz/vol/deploy_cockpit-pg")"
pruefe "nichts gelöscht"                       "nein" "$(ja_wenn grep -qE 'volume (rm|prune)' <(aufrufe))"
pruefe "Ort gespeichert"                       "PLATTFORM_KONSOLE=$T/neu" "$(grep '^PLATTFORM_KONSOLE=' "$KONF")"
pruefe "übrige Angaben unangetastet"           "PLATTFORM_BIND=10.0.0.5" "$(grep '^PLATTFORM_BIND=' "$KONF")"
pruefe "sagt, was als Nächstes kommt"          "ja" "$(ja_wenn grep -q 'plattform-aufbau.sh up$' <<<"$A")"
pruefe "…und wie es zurückgeht"                "ja" "$(ja_wenn grep -q "up --konsole $REPO_T/cockpit" <<<"$A")"

neu_aufrufe
A="$(lauf konsole-umziehen "$T/neu")"
pruefe "zweiter Lauf: läuft durch"             "ja" "$(ja_wenn grep -q 'Die Konsole ist umgezogen' <<<"$A")"
pruefe "…kopiert nichts mehr"                  "nein" "$(ja_wenn grep -q 'cp -a' <(aufrufe))"

neu_aufrufe
A="$(lauf restart)"
pruefe "danach startet die Konsole aus dem neuen Checkout" "ja" \
  "$(ja_wenn grep -q "^MAGISTER_DIR=$REPO_T docker compose --project-directory $T/neu/deploy .* restart" <(aufrufe))"

printf '\n\033[1m10 · Keine oder mehrere alte Datenbanken: Abbruch, nichts angefasst\033[0m\n'
rm -f "$T/dz/vol/"*
konsole "$T/frisch" "name: cockpit"
neu_aufrufe
A="$(lauf konsole-umziehen "$T/frisch")"
pruefe "kein altes Volume: Abbruch"            "ja" "$(ja_wenn grep -q 'Kein altes Volume' <<<"$A")"
pruefe "…mit dem Weg für eine neue Installation" "ja" "$(ja_wenn grep -q "up --konsole $T/frisch" <<<"$A")"
echo "deploy postgres" > "$T/dz/vol/deploy_cockpit-pg"
echo "anderes postgres" > "$T/dz/vol/anderes_cockpit-pg"
neu_aufrufe
A="$(lauf konsole-umziehen "$T/frisch")"
pruefe "mehrere alte Volumes: Abbruch"         "ja" "$(ja_wenn grep -q 'Mehrere alte Volumes' <<<"$A")"
pruefe "…kein Stack angehalten"                "nein" "$(ja_wenn grep -q ' down' <(aufrufe))"
pruefe "…nichts kopiert"                       "nein" "$(ja_wenn test -e "$T/frisch/deploy/.env")"

printf '\n'
if [ "$ROT" -eq 0 ]; then
  printf '\033[32m%d bestanden, 0 gescheitert\033[0m\n' "$GRUEN"
  exit 0
fi
printf '\033[31m%d bestanden, %d gescheitert\033[0m\n' "$GRUEN" "$ROT"
exit 1
