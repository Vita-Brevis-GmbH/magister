#!/usr/bin/env bash
# Wo die Konsole liegt (scripts/lib/konsole-pfad.sh) — und dass
# plattform-aufbau.sh sie umzieht, ohne etwas zu verlieren.
#
# Warum es diesen Test gibt: die Konsole ist aus cockpit/ in einen eigenen
# Checkout (vitabrevis-cockpit) gezogen, und cockpit/ ist aus Magister
# entfernt. Wählt ein Skript einen anderen Ort als das nächste, baut `up` die
# Oberfläche im einen Checkout und Caddy hängt den anderen ein — und startet
# die Konsole im neuen Checkout ohne ihre Datenbank, kennt die Datenebene
# danach keinen Kunden mehr. Ein Host, der noch nicht umgezogen ist, hat nach
# dem Pull nur noch die unversionierten Reste in cockpit/ (.env, certs/) und
# keine Compose-Datei mehr, mit der sich der alte Stack anhalten liesse.
#
# Ohne Docker und ohne Netz: die Pfade sind Verzeichnisse unter einem
# Arbeitsordner, plattform-aufbau.sh läuft als Kopie in einem nachgebauten
# Repo, und `docker` ist eine Attrappe, die jeden Aufruf mitschreibt. Volumes
# sind darin Dateien mit Projekt und Inhalt, laufende Container Dateien je
# Projekt mit ihren Diensten.
#
#   ./scripts/tests/konsole-pfad.test.sh

set -uo pipefail
# Was die Umgebung des Aufrufers sagt, gilt hier nicht.
unset PLATTFORM_KONSOLE PLATTFORM_KONF COMPOSE_FILE

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
  mkdir -p "$1/deploy" "$1/scripts"
  { [ -n "${2:-}" ] && printf '%s\n' "$2"; printf 'services: {}\n'; } > "$1/deploy/docker-compose.yml"
  printf 'services: {}\n' > "$1/deploy/docker-compose.plattform.yml"
  # scripts/cockpit.sh als Attrappe (vitabrevis-cockpit ADR 0009): schreibt
  # jeden Aufruf mit, kennt die Schnittstelle 1. `pruefen` scheitert, solange
  # $DZ/pruefen-scheitert da ist; `anlegen` legt das Volume an wie Compose.
  # Was das echte Skript tut, prüft vitabrevis-cockpit (scripts/tests/) und
  # hier plattform-konsole.test.sh.
  cat > "$1/scripts/cockpit.sh" <<'ATTRAPPE'
#!/usr/bin/env bash
echo "MAGISTER_DIR=${MAGISTER_DIR:-} $0 $*" >> "$DZ/aufrufe"
case "${1:-}" in
  schnittstelle) echo 1 ;;
  pruefen) if [ -f "$DZ/pruefen-scheitert" ]; then cat "$DZ/pruefen-scheitert" >&2; exit 1; fi ;;
  anlegen) [ -f "$DZ/vol/cockpit_cockpit-pg" ] || echo "cockpit leer" > "$DZ/vol/cockpit_cockpit-pg" ;;
esac
exit 0
ATTRAPPE
}

# --- Arbeitsplatz: Magister, ein Checkout daneben, der Klon unter „/opt" ----
WS="$T/ws"
MAG="$WS/magister"
mkdir -p "$MAG"
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

printf '\n\033[1m1 · Rangfolge: Umgebung → gespeichert → (dev: daneben) → /opt/cockpit/src\033[0m\n'
A="$(PLATTFORM_KONSOLE="$T/eigen" waehle "$T/conf/plattform.conf")"
pruefe "Umgebung schlägt die Konfiguration"    "$T/eigen"              "$(pfad "$A")"
A="$(waehle "$T/conf/plattform.conf")"
pruefe "gespeichert schlägt den Rückfall"      "$T/gespeichert"        "$(pfad "$A")"
pruefe "…und sagt, woher"                      "gespeichert in $T/conf/plattform.conf" "${A#*|}"
A="$(waehle "$T/conf/leer.conf")"
pruefe "ohne Angabe: der Klon unter /opt"      "$T/opt/cockpit/src"    "$(pfad "$A")"
pruefe "…als Vorgabe"                          "Vorgabe"               "${A#*|}"
A="$(waehle "")"
pruefe "ohne Konfigurationsdatei ebenso"       "$T/opt/cockpit/src"    "$(pfad "$A")"
A="$(waehle "" dev)"
pruefe "Entwicklerrechner: der Checkout daneben" "$WS/vitabrevis-cockpit" "$(pfad "$A")"

# Den Rückfall auf cockpit/ im Magister-Repo gibt es nicht mehr — auch dann
# nicht, wenn dort (von Hand zurückgeholt) wieder eine Compose-Datei liegt.
konsole "$MAG/cockpit"
pruefe "cockpit/ im Magister-Repo zählt nicht mehr" "$T/opt/cockpit/src" "$(pfad "$(waehle "")")"
pruefe "…auch nicht auf dem Entwicklerrechner"  "$WS/vitabrevis-cockpit" "$(pfad "$(waehle "" dev)")"
rm -r "$MAG/cockpit"

mv "$T/opt/cockpit/src" "$T/klon-weg"
A="$(waehle "")"
pruefe "nichts gefunden: Fehler statt Raten"   "FEHLER"                "$(pfad "$A")"
pruefe "…mit dem Weg zum Klon"                 "ja" "$(ja_wenn grep -q 'git clone .*vitabrevis-cockpit' <<<"$A")"
pruefe "…ohne Umzug, wo es nichts umzuziehen gibt" "nein" "$(ja_wenn grep -q 'konsole-umziehen' <<<"$A")"
# Ein Host vor dem Umzug: vom alten Ort ist nur der unversionierte Rest da.
mkdir -p "$MAG/cockpit/deploy"
printf 'COCKPIT_BOOTSTRAP_TOKEN=alt\n' > "$MAG/cockpit/deploy/.env"
A="$(waehle "")"
pruefe "Rest am alten Ort: weiterhin kein Rückfall" "FEHLER"           "$(pfad "$A")"
pruefe "…aber der Hinweis auf den Umzug"       "ja" \
  "$(ja_wenn grep -qF "konsole-umziehen $T/opt/cockpit/src" <<<"$A")"
rm -r "$MAG/cockpit"
mv "$WS/vitabrevis-cockpit" "$T/daneben-weg"
A="$(waehle "" dev)"
pruefe "Entwicklerrechner ohne alles: Fehler nennt beide Orte" "ja" \
  "$(ja_wenn grep -qF "fehlt in $WS/vitabrevis-cockpit und $T/opt/cockpit/src" <<<"$A")"
mv "$T/daneben-weg" "$WS/vitabrevis-cockpit"
mv "$T/klon-weg" "$T/opt/cockpit/src"

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
konsole "$T/ohne-name"
pruefe "ohne name: heisst das Projekt deploy"  "deploy"                "$(projekt "$T/ohne-name")"
pruefe "alter Ort ohne Compose-Datei: ebenso deploy" "deploy"          "$(projekt "$MAG/cockpit")"
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
# Der Klon unter „/opt" — in der Kopie umgelenkt, damit der Test nie einen
# echten Checkout auf dieser Maschine findet oder anfasst.
KLON="$T/klon"
sed -i "s|^KONSOLE_KLON=.*|KONSOLE_KLON=\"$KLON\"|" "$REPO_T/scripts/lib/konsole-pfad.sh"
grep -qxF "KONSOLE_KLON=\"$KLON\"" "$REPO_T/scripts/lib/konsole-pfad.sh" \
  || { echo "KONSOLE_KLON liess sich in der Kopie nicht umlenken" >&2; exit 1; }
# Ein Verlauf wie im echten Repo: cockpit/ erst versioniert, dann entfernt.
# Daraus nennt konsole-umziehen den Stand für den Weg zurück.
git_t() {
  git -C "$REPO_T" -c user.name=Test -c user.email=test@example.ch -c commit.gpgsign=false \
    "$@" >/dev/null 2>&1
}
git_t init -q
mkdir -p "$REPO_T/cockpit/deploy"
printf 'services: {}\n' > "$REPO_T/cockpit/deploy/docker-compose.yml"
git_t add cockpit && git_t commit -q -m "Konsole in cockpit/"
git_t rm -q -r cockpit && git_t commit -q -m "Konsole entfernt"
ENTFERNT="$(git -C "$REPO_T" log -1 --format=%h 2>/dev/null)"
# Der Host vor dem Umzug, mit diesem Stand: in cockpit/ liegen nur noch die
# unversionierten Reste — keine Compose-Datei, keine Caddyfile.
ALT="$REPO_T/cockpit/deploy"
mkdir -p "$ALT/certs"
printf 'COCKPIT_BOOTSTRAP_TOKEN=alt\n' > "$ALT/.env"; chmod 600 "$ALT/.env"
printf 'alt\n' > "$ALT/certs/console.pem"; printf 'alt\n' > "$ALT/certs/root.pem"

ROOT="$T/plattform"
KONF="$ROOT/plattform.conf"
mkdir -p "$ROOT" "$T/bin" "$T/dz/vol" "$T/dz/laeuft"

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
# leer oder postgres). Laufende Container eines Projekts stehen in
# $DZ/laeuft/<projekt>, ein Dienst je Zeile; `compose -p <projekt> down`
# räumt die Datei weg. Jeder Aufruf landet mit MAGISTER_DIR in $DZ/aufrufe.
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
esac
if [ "${1:-}" = "ps" ]; then
  # Gefiltert nach Projekt oder nach Volume (dann das Projekt des Volumes).
  p=""
  for a in "$@"; do
    case "$a" in
      label=com.docker.compose.project=*) p="${a#label=com.docker.compose.project=}" ;;
      volume=*) [ -f "$DZ/vol/${a#volume=}" ] && p="$(cut -d' ' -f1 "$DZ/vol/${a#volume=}")" ;;
    esac
  done
  [ -n "$p" ] && [ -f "$DZ/laeuft/$p" ] || exit 0
  case "$*" in
    *com.docker.compose.service*) cat "$DZ/laeuft/$p" ;;
    *) sed "s/.*/$p-&-1/" "$DZ/laeuft/$p" ;;
  esac
  exit 0
fi
case "$*" in
  "compose -p "*" down"*)
    # Wo und womit Compose gerufen wurde: aus einem Ordner mit Compose-Datei
    # oder mit COMPOSE_FILE läse es eine Datei und meinte deren Dienste.
    printf '%s\n' "$PWD" > "$DZ/down-ort"
    [ -n "${COMPOSE_FILE+x}" ] && printf '%s\n' "$COMPOSE_FILE" > "$DZ/down-compose-file"
    rm -f "$DZ/laeuft/$3" ;;
  *"up --no-start postgres"*)
    [ -f "$DZ/vol/cockpit_cockpit-pg" ] || echo "cockpit leer" > "$DZ/vol/cockpit_cockpit-pg" ;;
esac
exit 0
X
chmod +x "$T/bin/docker"
aufrufe() { cat "$T/dz/aufrufe" 2>/dev/null; }
neu_aufrufe() { : > "$T/dz/aufrufe"; rm -f "$T/dz/down-ort" "$T/dz/down-compose-file"; }
alte_konsole_laeuft() { printf 'api\ncaddy\npostgres\n' > "$T/dz/laeuft/deploy"; }

printf '\n\033[1m4 · Host vor dem Umzug, dieser Stand ausgecheckt: cockpit/ hat nur noch .env und certs\033[0m\n'
A="$(lauf konfig)"
pruefe "ohne Angabe: der Klon, nicht cockpit/" "$KLON"                 "$(wert KONSOLE_PFAD "$A")"
pruefe "…noch nicht geklont: der Grund steht da" "ja" \
  "$(ja_wenn grep -q "Keine Konsole gefunden" <<<"$A")"
pruefe "…mit dem Weg: erst umziehen"           "ja" "$(ja_wenn grep -qF "konsole-umziehen $KLON" <<<"$A")"
neu_aufrufe
A="$(lauf restart)"
pruefe "restart ohne Klon: Abbruch"            "ja" "$(ja_wenn grep -q "Keine Konsole gefunden" <<<"$A")"
pruefe "…bevor Docker gefragt wird"            "nein" "$(ja_wenn test -s "$T/dz/aufrufe")"
konsole "$KLON" "name: cockpit"
A="$(lauf konfig)"
pruefe "geklont: der Klon gilt"                "$KLON"                 "$(wert KONSOLE_PFAD "$A")"
pruefe "…Projekt cockpit"                      "cockpit"               "$(wert KONSOLE_PROJEKT "$A")"
pruefe "…ohne Fehler"                          "nein" "$(ja_wenn grep -q "Keine Konsole gefunden" <<<"$A")"

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
pruefe "--konsole \"\": zurück zur Automatik"    "$KLON"                 "$(wert KONSOLE_PFAD "$A")"
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
pruefe "Rest am alten Ort ist kein Ziel"       "ja" "$(ja_wenn grep -q 'kein Checkout von vitabrevis-cockpit' <<<"$A")"
# Jemand hat vitabrevis-cockpit an den alten Ort geklont.
konsole "$REPO_T/cockpit" "name: cockpit"
A="$(lauf konsole-umziehen "$REPO_T/cockpit")"
pruefe "Ziel ist der alte Ort: Abbruch"        "ja" "$(ja_wenn grep -q 'bisherige Ort' <<<"$A")"
rm -f "$ALT/docker-compose.yml" "$ALT/docker-compose.plattform.yml"
pruefe "…und Docker wurde nie gefragt"         "nein" "$(ja_wenn test -s "$T/dz/aufrufe")"

printf '\n\033[1m7 · Schutz: Klon da, Umgebung und Daten noch am alten Ort — kein Start\033[0m\n'
printf 'PLATTFORM_DOMAIN=example.ch\nPLATTFORM_BIND=10.0.0.5\n' > "$KONF"
echo "deploy postgres" > "$T/dz/vol/deploy_cockpit-pg"
alte_konsole_laeuft
neu_aufrufe
A="$(lauf restart)"
pruefe ".env nur im Rest am alten Ort: Abbruch" "ja" "$(ja_wenn grep -qF "konsole-umziehen $KLON" <<<"$A")"
pruefe "…mit dem Grund"                        "ja" "$(ja_wenn grep -qF "Umgebung (.env mit den Geheimnissen) liegt aber noch am alten Ort $ALT" <<<"$A")"
pruefe "…und nichts neu gestartet"             "nein" "$(ja_wenn grep -q ' restart' <(aufrufe))"
pruefe "…die alte Konsole läuft weiter"        "ja" "$(ja_wenn test -f "$T/dz/laeuft/deploy")"

konsole "$T/schutz" "name: cockpit"
printf 'PLATTFORM_KONSOLE=%s\n' "$T/schutz" > "$KONF"
printf 'COCKPIT_BOOTSTRAP_TOKEN=x\n' > "$T/schutz/deploy/.env"
neu_aufrufe
A="$(lauf restart)"
pruefe "Volume fehlt, altes da: Abbruch"       "ja" "$(ja_wenn grep -q "alten Volume deploy_cockpit-pg" <<<"$A")"
pruefe "…mit dem Hinweis auf konsole-umziehen" "ja" "$(ja_wenn grep -q "konsole-umziehen $T/schutz" <<<"$A")"
pruefe "…und nichts neu gestartet"             "nein" "$(ja_wenn grep -q ' restart' <(aufrufe))"

# Der Checkout wurde weggeräumt und neu geklont: Datenbank da, .env nicht.
# Ein Start legte eine neue .env mit neuen Geheimnissen an. Der Host ist
# umgezogen und aufgeräumt – am alten Ort liegt keine .env mehr.
mv "$ALT/.env" "$T/alt.env.weg"
konsole "$T/neu-geklont" "name: cockpit"
printf 'PLATTFORM_KONSOLE=%s\n' "$T/neu-geklont" > "$KONF"
# Den Schutz hält die Konsole selbst (cockpit.sh pruefen); hier zählt, dass
# Magister ihn vor jedem Start fragt und dann nichts anfasst.
echo "cockpit postgres" > "$T/dz/vol/cockpit_cockpit-pg"
echo " !! Die Datenbank der Konsole besteht, ihre Umgebung fehlt (Attrappe)" > "$T/dz/pruefen-scheitert"
neu_aufrufe
A="$(lauf restart)"
pruefe "Konsole meldet: .env fehlt – Abbruch"  "ja" "$(ja_wenn grep -qF "ihre Umgebung fehlt (Attrappe)" <<<"$A")"
pruefe "…gefragt im neuen Checkout"            "ja" "$(ja_wenn grep -qF "$T/neu-geklont/scripts/cockpit.sh pruefen" <(aufrufe))"
pruefe "…nur eine Meldung"                     "nein" "$(ja_wenn grep -q "Abbruch (Code" <<<"$A")"
pruefe "…und nichts neu gestartet"             "nein" "$(ja_wenn grep -q ' restart' <(aufrufe))"
rm -f "$T/dz/pruefen-scheitert"
printf 'COCKPIT_BOOTSTRAP_TOKEN=x\n' > "$T/neu-geklont/deploy/.env"
neu_aufrufe
A="$(lauf restart)"
pruefe ".env zurückgelegt: Start"              "ja" "$(ja_wenn grep -q ' restart' <(aufrufe))"
rm -f "$T/dz/vol/cockpit_cockpit-pg"
# Neue Installation: weder Datenbank noch .env – write_env legt sie an.
konsole "$T/frisch" "name: cockpit"
printf 'PLATTFORM_KONSOLE=%s\n' "$T/frisch" > "$KONF"
mv "$T/dz/vol/deploy_cockpit-pg" "$T/dz/deploy_cockpit-pg.weg"
neu_aufrufe
A="$(lauf restart)"
pruefe "neue Installation ohne .env: kein Abbruch" "nein" "$(ja_wenn grep -q "ihre Umgebung fehlt" <<<"$A")"
pruefe "…und gestartet"                        "ja" "$(ja_wenn grep -q ' restart' <(aufrufe))"
mv "$T/dz/deploy_cockpit-pg.weg" "$T/dz/vol/deploy_cockpit-pg"
mv "$T/alt.env.weg" "$ALT/.env"

printf '\n\033[1m8 · konsole-umziehen ohne die alten Compose-Dateien: anhalten über das Projekt, kopieren, merken\033[0m\n'
printf 'PLATTFORM_DOMAIN=example.ch\nPLATTFORM_BIND=10.0.0.5\n' > "$KONF"
mkdir -p "$KLON/deploy/certs"
printf 'neu\n' > "$KLON/deploy/certs/console.pem"   # vorhanden: bleibt
alte_konsole_laeuft
neu_aufrufe
# Eine COMPOSE_FILE in der Umgebung darf das Anhalten nicht umlenken.
UMGEBUNG=(COMPOSE_FILE="$T/fremd/docker-compose.yml")
A="$(lauf konsole-umziehen "$KLON")"
UMGEBUNG=()
pruefe "läuft durch"                           "ja" "$(ja_wenn grep -q 'Die Konsole ist umgezogen' <<<"$A")"
pruefe "alter Stack: down über das Projekt aus dem Volume-Label" "ja" \
  "$(ja_wenn grep -qE ' docker compose -p deploy down$' <(aufrufe))"
pruefe "…ohne Compose-Datei"                   "0" "$(grep -E ' -p deploy ' <(aufrufe) | grep -c -- ' -f ')"
pruefe "…aus /, wo Compose keine Datei findet" "/"  "$(cat "$T/dz/down-ort" 2>/dev/null)"
pruefe "…ohne COMPOSE_FILE"                    "nein" "$(ja_wenn test -e "$T/dz/down-compose-file")"
pruefe "…ohne -v"                              "nein" "$(ja_wenn grep -qE ' down .*-v|--volumes' <(aufrufe))"
pruefe "die alte Konsole ist angehalten"       "nein" "$(ja_wenn test -f "$T/dz/laeuft/deploy")"
pruefe ".env aus dem Rest übernommen"          "COCKPIT_BOOTSTRAP_TOKEN=alt" "$(cat "$KLON/deploy/.env")"
pruefe "…mit ihren Rechten"                    "600" "$(stat -c %a "$KLON/deploy/.env")"
pruefe "fehlendes Zertifikat übernommen"       "alt" "$(cat "$KLON/deploy/certs/root.pem")"
pruefe "vorhandenes nicht überschrieben"       "neu" "$(cat "$KLON/deploy/certs/console.pem")"
pruefe "Ziel-Volume über die Konsole angelegt (cockpit.sh anlegen)" "ja" \
  "$(ja_wenn grep -qx "MAGISTER_DIR=$REPO_T $KLON/scripts/cockpit.sh anlegen" <(aufrufe))"
pruefe "Datenbank kopiert, Quelle nur lesend"  "ja" \
  "$(ja_wenn grep -q 'run --rm -v deploy_cockpit-pg:/quelle:ro -v cockpit_cockpit-pg:/ziel postgres:16 cp -a /quelle/. /ziel/' <(aufrufe))"
pruefe "…und im Ziel angekommen"               "cockpit postgres" "$(cat "$T/dz/vol/cockpit_cockpit-pg")"
pruefe "altes Volume bleibt"                   "deploy postgres" "$(cat "$T/dz/vol/deploy_cockpit-pg")"
pruefe "nichts gelöscht"                       "nein" "$(ja_wenn grep -qE 'volume (rm|prune)' <(aufrufe))"
pruefe "der Rest am alten Ort bleibt"          "COCKPIT_BOOTSTRAP_TOKEN=alt" "$(cat "$ALT/.env")"
pruefe "Ort gespeichert"                       "PLATTFORM_KONSOLE=$KLON" "$(grep '^PLATTFORM_KONSOLE=' "$KONF")"
pruefe "übrige Angaben unangetastet"           "PLATTFORM_BIND=10.0.0.5" "$(grep '^PLATTFORM_BIND=' "$KONF")"
pruefe "sagt, was als Nächstes kommt"          "ja" "$(ja_wenn grep -q 'plattform-aufbau.sh up$' <<<"$A")"
pruefe "…wie es zurückgeht: cockpit/ aus dem Stand davor" "ja" \
  "$(ja_wenn grep -qF "git -C $REPO_T archive ${ENTFERNT}^ cockpit | tar -x -C $REPO_T" <<<"$A")"
pruefe "…und von dort starten"                 "ja" "$(ja_wenn grep -qF "up --konsole $REPO_T/cockpit" <<<"$A")"

neu_aufrufe
A="$(lauf konsole-umziehen "$KLON")"
pruefe "zweiter Lauf: läuft durch"             "ja" "$(ja_wenn grep -q 'Die Konsole ist umgezogen' <<<"$A")"
pruefe "…hält nichts mehr an"                  "nein" "$(ja_wenn grep -q ' down' <(aufrufe))"
pruefe "…kopiert nichts mehr"                  "nein" "$(ja_wenn grep -q 'cp -a' <(aufrufe))"

neu_aufrufe
A="$(lauf restart)"
pruefe "danach startet die Konsole aus dem Klon" "ja" \
  "$(ja_wenn grep -qx "MAGISTER_DIR=$REPO_T $KLON/scripts/cockpit.sh restart" <(aufrufe))"

printf '\n\033[1m9 · Was nicht sicher zur alten Konsole gehört, fasst konsole-umziehen nicht an\033[0m\n'
rm -f "$T/dz/vol/"* "$T/dz/laeuft/"*
echo "deploy postgres" > "$T/dz/vol/deploy_cockpit-pg"
printf 'api\ncaddy\npostgres\nwebshop\n' > "$T/dz/laeuft/deploy"
konsole "$T/fremd-ziel" "name: cockpit"
neu_aufrufe
A="$(lauf konsole-umziehen "$T/fremd-ziel")"
pruefe "fremder Dienst im alten Projekt: Abbruch" "ja" "$(ja_wenn grep -q 'noch anderes (webshop)' <<<"$A")"
pruefe "…kein Stack angehalten"                "nein" "$(ja_wenn grep -q ' down' <(aufrufe))"
pruefe "…nichts kopiert"                       "nein" "$(ja_wenn test -e "$T/fremd-ziel/deploy/.env")"
pruefe "…kein Volume angelegt"                 "nein" "$(ja_wenn grep -q 'cockpit.sh anlegen' <(aufrufe))"

# Der Rest am alten Ort ist weggeräumt, und im Ziel liegt keine .env.
alte_konsole_laeuft
mv "$REPO_T/cockpit" "$T/rest-weg"
neu_aufrufe
A="$(lauf konsole-umziehen "$T/fremd-ziel")"
pruefe "keine .env, weder alt noch neu: Abbruch" "ja" "$(ja_wenn grep -q 'Die Umgebung der Konsole fehlt' <<<"$A")"
pruefe "…kein Stack angehalten"                "nein" "$(ja_wenn grep -q ' down' <(aufrufe))"
pruefe "…kein Volume angelegt"                 "nein" "$(ja_wenn grep -q 'cockpit.sh anlegen' <(aufrufe))"
# Liegt die .env schon im Ziel, geht es auch ohne den Rest.
printf 'COCKPIT_BOOTSTRAP_TOKEN=gerettet\n' > "$T/fremd-ziel/deploy/.env"
neu_aufrufe
A="$(lauf konsole-umziehen "$T/fremd-ziel")"
pruefe "ohne Rest, .env im Ziel: läuft durch"  "ja" "$(ja_wenn grep -q 'Die Konsole ist umgezogen' <<<"$A")"
pruefe "…alter Stack über das Projekt angehalten" "ja" \
  "$(ja_wenn grep -qE ' docker compose -p deploy down$' <(aufrufe))"
pruefe "…Datenbank kopiert"                    "cockpit postgres" "$(cat "$T/dz/vol/cockpit_cockpit-pg")"
pruefe "…die .env im Ziel unangetastet"        "COCKPIT_BOOTSTRAP_TOKEN=gerettet" "$(cat "$T/fremd-ziel/deploy/.env")"
mv "$T/rest-weg" "$REPO_T/cockpit"

printf '\n\033[1m10 · Keine oder mehrere alte Datenbanken: Abbruch, nichts angefasst\033[0m\n'
rm -f "$T/dz/vol/"* "$T/dz/laeuft/"*
konsole "$T/frisch" "name: cockpit"
neu_aufrufe
A="$(lauf konsole-umziehen "$T/frisch")"
pruefe "kein altes Volume: Abbruch"            "ja" "$(ja_wenn grep -q 'Kein altes Volume' <<<"$A")"
pruefe "…mit dem Weg für eine neue Installation" "ja" "$(ja_wenn grep -q "up --konsole $T/frisch" <<<"$A")"
echo "deploy postgres" > "$T/dz/vol/deploy_cockpit-pg"
echo "anderes postgres" > "$T/dz/vol/anderes_cockpit-pg"
alte_konsole_laeuft
neu_aufrufe
A="$(lauf konsole-umziehen "$T/frisch")"
pruefe "mehrere alte Volumes: Abbruch"         "ja" "$(ja_wenn grep -q 'Mehrere alte Volumes' <<<"$A")"
pruefe "…kein Stack angehalten"                "nein" "$(ja_wenn grep -q ' down' <(aufrufe))"
pruefe "…nichts kopiert"                       "nein" "$(ja_wenn test -e "$T/frisch/deploy/.env")"

printf '\n\033[1m11 · Checkout der Konsole zu alt für diesen Stand von Magister\033[0m\n'
rm -f "$T/dz/vol/"* "$T/dz/laeuft/"*
konsole "$T/alt-stand" "name: cockpit"
rm "$T/alt-stand/scripts/cockpit.sh"
printf 'PLATTFORM_DOMAIN=example.ch\nPLATTFORM_BIND=10.0.0.5\nPLATTFORM_KONSOLE=%s\n' "$T/alt-stand" > "$KONF"
neu_aufrufe
A="$(lauf restart)"
pruefe "ohne scripts/cockpit.sh: Abbruch"      "ja" "$(ja_wenn grep -qF "ist älter als dieser Stand von Magister: scripts/cockpit.sh fehlt" <<<"$A")"
pruefe "…mit dem Befehl zum Aktualisieren"     "ja" "$(ja_wenn grep -qF "git -C $T/alt-stand pull" <<<"$A")"
pruefe "…bevor Docker gefragt wird"            "nein" "$(ja_wenn test -s "$T/dz/aufrufe")"
konsole "$T/alt-stand" "name: cockpit"
sed -i 's/schnittstelle) echo 1/schnittstelle) echo 7/' "$T/alt-stand/scripts/cockpit.sh"
A="$(lauf restart)"
pruefe "andere Fassung der Schnittstelle: Abbruch" "ja" "$(ja_wenn grep -qF "spricht die Schnittstelle 1 nicht (sie kann: 7)" <<<"$A")"
pruefe "…nichts neu gestartet"                 "nein" "$(ja_wenn grep -q ' restart' <(aufrufe))"
rm "$T/alt-stand/scripts/cockpit.sh"
A="$(lauf konsole-umziehen "$T/alt-stand")"
pruefe "konsole-umziehen in einen zu alten Stand: Abbruch" "ja" "$(ja_wenn grep -q "zu alter Stand von vitabrevis-cockpit" <<<"$A")"

printf '\n'
if [ "$ROT" -eq 0 ]; then
  printf '\033[32m%d bestanden, 0 gescheitert\033[0m\n' "$GRUEN"
  exit 0
fi
printf '\033[31m%d bestanden, %d gescheitert\033[0m\n' "$GRUEN" "$ROT"
exit 1
