#!/usr/bin/env bash
# Betrieb der Magister-Plattform aus dem Cockpit (Host-Agent v2, ADR-0028).
#
# Der Einstiegspunkt nach dem Vertrag `betrieb/v1`. Der Host-Agent des
# Cockpits kennt keine Befehle von Magister: er ruft nur dieses Skript mit
# einem festen Unterbefehl auf — als root, im Checkout, ohne Terminal, mit
# nichts als PATH, LANG und BETRIEB_AUFTRAG in der Umgebung:
#
#   scripts/betrieb.sh stand                      Version, Commit, Health, ob `zurueck` geht
#   scripts/betrieb.sh sichern                    Sicherung der Datenbank, verschlüsselt
#   scripts/betrieb.sh aktualisieren --ref <ref>  Branch, Tag oder Commit von origin
#   scripts/betrieb.sh aktualisieren --ref <ref> --bundle <datei> --commit <sha>
#                                                 derselbe Ablauf, der Stand kommt aus dem
#                                                 git-Bundle des Cockpits (Repo privat)
#   scripts/betrieb.sh zurueck                    einmal zurück auf den Stand vor dem Update
#   scripts/betrieb.sh neustart                   Datenebene neu starten (ohne Neubau) + Health
#
# Auf stdout steht genau EINE Zeile JSON: die Antwort ans Cockpit. Alles
# andere — auch die Ausgaben von plattform-aufbau.sh — geht nach stderr, ins
# Journal des Agenten. Exit-Codes:
#
#   0 ok · 1 gescheitert und selbst zurückgefallen (läuft auf dem alten Stand)
#   2 gescheitert, Zustand von Hand klären (die Meldung nennt den nächsten Schritt)
#   3 abgelehnt, nichts geändert · 4 belegt (eine andere Aktion läuft)
#
# Ein Update ist: Sperre → Ref prüfen (git fetch, Branch/Tag/Commit, nicht
# älter als der laufende Stand und nur ein Nachfahre davon: eine andere Linie,
# etwa ein anderer Branch, → Exit 3) → Sicherung → umschalten →
# plattform-aufbau.sh update → Health bis 5 min → sonst selbst zurück:
# Datenbank aus der eben gemachten Sicherung, alter Commit, plattform-aufbau.sh
# update, Exit 1.
#
# `stand` meldet die Herkunft des Checkouts (`herkunft`: Branch bzw.
# losgelöst); das Cockpit nimmt den Branch als Vorgabe seiner Quelle.
#
# Repo privat (ADR-0028 Nachtrag): nur das Cockpit hat einen GitHub-Zugang. Es
# löst die Ref auf und gibt den Stand als git-Bundle mit; der Host-Agent prüft
# dessen SHA-256 und ruft `aktualisieren --ref <ref> --bundle <datei> --commit
# <sha>` auf. Dann wird origin NIE kontaktiert: `git bundle verify` → `git
# fetch <bundle> <commit>` → der Commit muss zum Stand des Bundles gehören
# (sonst Exit 3, nichts geändert). Ist die Ref ein Branch, wird er lokal
# angehängt — ohne Upstream —, sonst losgelöst. Tags des Bundles kommen mit
# (die Version ist `git describe`). Ohne --bundle wie bisher von origin.
# Einen Pull-Zugang für Images gibt der Agent als DOCKER_CONFIG mit: docker
# erbt ihn, dieses Skript setzt und nennt ihn nie.
#
# Die Sicherung macht der Container pg-backup, mit dem öffentlichen
# age-Schlüssel (ADR-0016 D9) — dieselbe wie vor jeder Migration, nur MIT
# Eigentümern und Rechten (BACKUP_ART=rueckfall), damit die Kundenschemas
# nach dem Einspielen wieder ihren Rollen gehören. Einspielen kann sie nur,
# wer den PRIVATEN Schlüssel hat; in Produktion liegt er nicht auf dem Host
# (ADR-0016 D2). Deshalb gilt beim Rückfall:
#
#   * privater Schlüssel da  → Code UND Datenbank zurück (Daten seit dem Update
#                              gehen verloren, die bisherige Datenbank bleibt
#                              umbenannt liegen: <db>_vor_rueckfall_<zeit>);
#   * Schlüssel fehlt, Schemastand unverändert → nur der Code zurück;
#   * Schlüssel fehlt, Schemastand geändert → nichts automatisch, Exit 2: der
#     nächste Schritt (Schlüssel hinlegen, dann `zurueck`) steht in der Meldung.
#
# Was es NIE tut: den Checkout der Konsole anfassen (das Cockpit ist ein
# eigenes Produkt mit eigenem betrieb.sh), Images aus GHCR ziehen (gebaut wird
# aus diesem Checkout, wie beim Ops-Agenten), eine Datenbank löschen, die
# nicht eben selbst halb eingespielt wurde, Geheimnisse oder Ausgaben fremder
# Programme in die Meldung schreiben.
#
# Zeitlimit des Agenten: 30 min für aktualisieren/zurueck, 10 min sonst, 2 min
# für stand. Die Schritte haben eigene Grenzen darunter (siehe unten).

set -uo pipefail

# stdout gehört der Antwort; alles andere geht nach stderr.
exec 3>&1 1>&2

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ZIEL="${PLATTFORM_ROOT:-$REPO/plattform}"
COMPOSE_DIR="$REPO/deploy/compose"
AUFBAU="$REPO/scripts/plattform-aufbau.sh"
ZUSTAND_DIR="$ZIEL/betrieb"
ZUSTAND="$ZUSTAND_DIR/zustand"
# Derselbe Ort wie für den Prüfer (plattform-backup-pruefer.sh). In Produktion
# fehlt die Datei (docs/runbooks/prod-installation.md §7).
SCHLUESSEL="$ZIEL/certs/backup-age.key"
SPERRE="$REPO/.betrieb.lock"
# Im Container pg-backup (Volume `backups`), nicht auf dem Host.
SICHERUNGEN="/var/backups/magister"

#: Grenzen in Sekunden. Die Umgebung setzt sie nur in den Tests — der Agent
#: übergibt nichts ausser PATH, LANG und BETRIEB_AUFTRAG.
zahl() { [[ "${1:-}" =~ ^[0-9]{1,5}$ ]] && printf '%s' "$1" || printf '%s' "$2"; }
SICHERN_SEK="$(zahl "${BETRIEB_SICHERN_SEK:-}" 300)"
UPDATE_SEK="$(zahl "${BETRIEB_UPDATE_SEK:-}" 900)"
HEALTH_SEK="$(zahl "${BETRIEB_HEALTH_SEK:-}" 300)"
RUECKFALL_SEK="$(zahl "${BETRIEB_RUECKFALL_SEK:-}" 420)"
RUECKFALL_HEALTH_SEK="$(zahl "${BETRIEB_RUECKFALL_HEALTH_SEK:-}" 180)"

# Ohne Terminal und ohne HOME (systemd): git darf nicht nach Zugangsdaten
# fragen, plattform-aufbau.sh liest $HOME (set -u).
export HOME="${HOME:-/root}"
export GIT_TERMINAL_PROMPT=0
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes}"

AUFTRAG="${BETRIEB_AUFTRAG:-}"
[[ "$AUFTRAG" =~ ^[0-9A-Za-z-]{1,64}$ ]] || AUFTRAG="-"

say()  { printf '[betrieb %s] %s\n' "$AUFTRAG" "$*" >&2; }
warn() { printf '[betrieb %s] !  %s\n' "$AUFTRAG" "$*" >&2; }

# --- git ---------------------------------------------------------------------
# Der Agent läuft als root, der Checkout gehört dem Betriebsbenutzer. Ohne
# safe.directory verweigert git jede Arbeit („dubious ownership") — wie im
# Ops-Agenten (plattform-ops-agent.sh).
git_r() { git -c safe.directory="$REPO" -C "$REPO" "$@"; }

#: Tag, `git describe` oder kurzer Commit.
version_von() {  # $1 = Commit
  git_r describe --tags --always "$1" 2>/dev/null || printf '%s' "${1:0:12}"
}

#: Vertrag betrieb/v1: Buchstabe oder Ziffer zuerst, höchstens 100 Zeichen,
#: ohne `..` und `@{`.
ref_gueltig() {  # $1 = Ref
  [[ "${1:-}" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$ ]] || return 1
  case "$1" in *..*|*@\{*) return 1 ;; esac
  return 0
}

#: Lokale Änderungen an versionierten Dateien. Unversionierte Dateien zählen
#: nicht (wie bei `git pull --ff-only`): ein Checkout, der sie überschriebe,
#: bricht ab, ohne etwas zu ändern.
lokale_aenderungen() {  # -> Anzahl, leer = git-Fehler
  local s
  s="$(git_r status --porcelain --untracked-files=no 2>/dev/null)" || return 1
  if [ -z "$s" ]; then printf '0'; else printf '%s\n' "$s" | wc -l | tr -d ' '; fi
}

#: Branch auf origin, dann Tag, dann Commit (hex) -> ZIEL_COMMIT, ZIEL_BRANCH.
ref_aufloesen() {  # $1 = Ref
  local c
  ZIEL_COMMIT=""; ZIEL_BRANCH=""
  if [ "$1" != "HEAD" ] && git_r check-ref-format --branch "$1" >/dev/null 2>&1 \
     && c="$(git_r rev-parse -q --verify "refs/remotes/origin/$1^{commit}" 2>/dev/null)"; then
    ZIEL_COMMIT="$c"; ZIEL_BRANCH="$1"; return 0
  fi
  if c="$(git_r rev-parse -q --verify "refs/tags/$1^{commit}" 2>/dev/null)"; then
    ZIEL_COMMIT="$c"; return 0
  fi
  if [[ "$1" =~ ^[0-9a-f]{7,40}$ ]] \
     && c="$(git_r rev-parse -q --verify "$1^{commit}" 2>/dev/null)"; then
    ZIEL_COMMIT="$c"; return 0
  fi
  return 1
}

#: HEAD auf $1 stellen — mit Branch angehängt, sonst losgelöst. Mit
#: `ohne-upstream` (Stand aus dem Bundle) hat der Branch keinen Upstream.
umschalten() {  # $1 = Commit, $2 = Branch (leer = losgelöst), $3 = ohne-upstream -> 0, wenn HEAD dort steht
  if [ -n "${2:-}" ]; then
    git_r checkout -q -B "$2" "$1" || return 1
    if [ "${3:-}" = "ohne-upstream" ]; then
      git_r branch -q --unset-upstream "$2" >/dev/null 2>&1 || true
    else
      git_r branch -q --set-upstream-to="origin/$2" "$2" >/dev/null 2>&1 || true
    fi
  else
    git_r checkout -q --detach "$1" || return 1
  fi
  [ "$(git_r rev-parse HEAD 2>/dev/null)" = "$1" ]
}

# --- Stand aus dem git-Bundle des Cockpits (Repo privat) -----------------------
BUNDLE_KOEPFE=""  # git bundle list-heads: je Zeile "<commit> <name>"
BUNDLE_FEHLER=""

#: Absoluter Pfad einer lesbaren, nicht leeren Datei — nie ein Remote-Name.
bundle_datei() {  # $1 = Angabe
  local d="${1:-}" ordner
  [ -n "$d" ] && [ -f "$d" ] && [ -r "$d" ] && [ -s "$d" ] || return 1
  ordner="$(cd "$(dirname "$d")" 2>/dev/null && pwd -P)" || return 1
  printf '%s/%s' "$ordner" "$(basename "$d")"
}

#: Bundle prüfen und den Commit daraus holen — ohne origin. Bis hier ist nichts
#: umgestellt (nur Objekte und Tags im Repo). -> 0 = Commit da und im Bundle.
bundle_holen() {  # $1 = Bundle (absolut), $2 = Commit (40 hex)
  local kopf name
  BUNDLE_KOEPFE=""; BUNDLE_FEHLER=""
  if ! git_r bundle verify "$1" >/dev/null; then
    BUNDLE_FEHLER="Bundle ungültig bzw. passt nicht zu diesem Checkout (git bundle verify)"
    return 1
  fi
  BUNDLE_KOEPFE="$(git_r bundle list-heads "$1" 2>/dev/null)"
  if [ -z "$BUNDLE_KOEPFE" ]; then
    BUNDLE_FEHLER="Bundle ohne Köpfe (git bundle list-heads)"; return 1
  fi
  if ! timeout 600 git -c safe.directory="$REPO" -C "$REPO" fetch --quiet --no-tags "$1" "$2" 9>&- \
     || ! git_r cat-file -e "$2^{commit}" 2>/dev/null; then
    BUNDLE_FEHLER="Commit ${2:0:12} fehlt im Bundle bzw. Bundle beschädigt"; return 1
  fi
  while read -r kopf name; do
    [[ "$kopf" =~ ^[0-9a-f]{40}$ ]] || continue
    if [ "$kopf" = "$2" ] || git_r merge-base --is-ancestor "$2" "$kopf" </dev/null 2>/dev/null; then
      # Tags des Bundles für `git describe`; bestehende werden nie überschrieben
      git_r fetch --quiet --no-tags "$1" 'refs/tags/*:refs/tags/*' </dev/null 9>&- 2>/dev/null \
        || warn "Nicht alle Tags aus dem Bundle übernommen (gleichnamige zeigen woanders hin)"
      return 0
    fi
  done <<<"$BUNDLE_KOEPFE"
  BUNDLE_FEHLER="Commit ${2:0:12} gehört nicht zum Stand des Bundles"
  return 1
}

bundle_kopf() {  # $1 = voller Name -> 0, wenn das Bundle ihn als Kopf hat
  local kopf name
  while read -r kopf name; do [ "$name" != "$1" ] || return 0; done <<<"$BUNDLE_KOEPFE"
  return 1
}

#: Ist die Ref ein Branch? -> Name des Branches, sonst nichts (losgelöst).
#: Commit und Tag (im Bundle oder lokal) losgelöst; Branch nur, wenn das
#: Bundle bzw. der Checkout ihn als Branch kennt — im Zweifel losgelöst.
bundle_branch() {  # $1 = Ref, $2 = Commit
  [ "$1" != "HEAD" ] || return 0
  if [[ "$1" =~ ^[0-9a-f]{7,40}$ && "$2" == "$1"* ]]; then return 0; fi
  git_r check-ref-format --branch "$1" >/dev/null 2>&1 || return 0
  if bundle_kopf "refs/tags/$1" || git_r rev-parse -q --verify "refs/tags/$1" >/dev/null 2>&1; then
    return 0
  fi
  if bundle_kopf "refs/heads/$1" \
     || git_r rev-parse -q --verify "refs/heads/$1" >/dev/null 2>&1 \
     || git_r rev-parse -q --verify "refs/remotes/origin/$1" >/dev/null 2>&1; then
    printf '%s' "$1"
  fi
  return 0
}

# --- Datenebene (Compose-Projekt magister) ------------------------------------
# Für ps/exec/restart/stop genügen die zwei Grunddateien; die Überlagerungen
# aus plattform-aufbau.sh (Bauen, Konsolen-Adresse) ändern daran nichts.
DC=(docker compose --project-directory "$COMPOSE_DIR"
    -f "$COMPOSE_DIR/docker-compose.yml" -f "$COMPOSE_DIR/docker-compose.plattform.yml")
dc()   { "${DC[@]}" "$@"; }
dc_t() { local s="$1"; shift; timeout --kill-after=10 "$s" "${DC[@]}" "$@"; }

#: Ein Name aus deploy/compose/.env — nur Bezeichner, keine Geheimnisse.
env_name() {  # $1 = Schlüssel, $2 = Vorgabe
  local w
  w="$(grep -m1 "^$1=" "$COMPOSE_DIR/.env" 2>/dev/null | cut -d= -f2-)"
  if [[ "$w" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then printf '%s' "$w"; else printf '%s' "$2"; fi
}
PG_USER="$(env_name POSTGRES_USER magister)"
PG_DB="$(env_name POSTGRES_DB magister)"
q() { printf '"%s"' "$1"; }  # Bezeichner, nur nach env_name/Muster

docker_da() { timeout 15 docker info >/dev/null 2>&1; }

HEALTHZ_PY="import json,urllib.request;print(json.load(urllib.request.urlopen('http://localhost:8000/healthz',timeout=5)).get('status',''))"

#: Jeder Dienst der Datenebene läuft (und ist gesund, wo er eine Prüfung hat),
#: und die API antwortet jetzt auf /healthz mit „ok".
gesund_einmal() {
  local dienste zeilen schlecht antwort
  GESUND_GRUND=""
  if ! dienste="$(dc_t 20 config --services 2>/dev/null)" || [ -z "$dienste" ]; then
    GESUND_GRUND="Compose-Konfiguration der Datenebene nicht lesbar"; return 1
  fi
  if ! zeilen="$(dc_t 20 ps --all --format '{{.Service}} {{.State}} {{.Health}}' 2>/dev/null)"; then
    GESUND_GRUND="docker compose ps gescheitert"; return 1
  fi
  schlecht="$(awk 'NR == FNR { if ($1 != "") soll[$1] = 1; next }
                   { zustand[$1] = $2; health[$1] = $3 }
                   END { for (d in soll)
                           if (zustand[d] != "running" || (health[d] != "" && health[d] != "healthy")) {
                             print d; exit } }' \
              <(printf '%s\n' "$dienste") <(printf '%s\n' "$zeilen"))"
  if [ -n "$schlecht" ]; then
    [[ "$schlecht" =~ ^[A-Za-z0-9_.-]{1,64}$ ]] || schlecht="?"
    GESUND_GRUND="$schlecht nicht bereit"; return 1
  fi
  antwort="$(dc_t 15 exec -T magister-api python -c "$HEALTHZ_PY" 2>/dev/null | tr -d '\r\n')"
  if [ "$antwort" != "ok" ]; then
    GESUND_GRUND="magister-api: /healthz nicht ok"; return 1
  fi
  return 0
}

gesund_warten() {  # $1 = Sekunden -> 0 = gesund; setzt GESUND
  local sek="$1" n=0 versuche start=$SECONDS
  versuche=$(( sek / 5 )); [ "$versuche" -ge 1 ] || versuche=1
  say "Health der Datenebene prüfen (bis $sek s)"
  while :; do
    n=$((n + 1))
    if gesund_einmal; then GESUND=true; say "Health ok"; return 0; fi
    if [ "$n" -ge "$versuche" ] || [ $((SECONDS - start)) -ge "$sek" ]; then break; fi
    sleep 5
  done
  GESUND=false
  say "Health nicht ok: $GESUND_GRUND"
  return 1
}

#: plattform-aufbau.sh mit Zeitgrenze; seine Ausgaben gehen nach stderr.
aufbau() {  # $1 = Sekunden, Rest = Argumente
  local sek="$1"; shift
  say "plattform-aufbau.sh $* (bis $sek s)"
  PLATTFORM_NICHT_FRAGEN=1 timeout --kill-after=30 "$sek" bash "$AUFBAU" "$@" </dev/null >&2
}

# --- Sicherung ---------------------------------------------------------------
datei_gueltig() {  # $1 = Name einer Sicherung im Volume
  [[ "${1:-}" =~ ^[a-z_][a-z0-9_]{0,62}-[0-9]{8}T[0-9]{6}Z(-rueckfall)?\.dump\.age$ ]]
}
datei_zeit() {  # magister-20261116T120000Z-rueckfall.dump.age -> 2026-11-16T12:00:00Z
  printf '%s' "$1" | sed -nE \
    's/^.*-([0-9]{4})([0-9]{2})([0-9]{2})T([0-9]{2})([0-9]{2})([0-9]{2})Z(-rueckfall)?\.dump\.age$/\1-\2-\3T\4:\5:\6Z/p'
}
iso_gueltig() { [[ "${1:-}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]]; }

#: Im Container: liegt die Datei da, und stimmt ihre Prüfsumme (die Zeile, die
#: backup.sh nach PRUEFSUMMEN.sha256 schreibt)? Läuft dort unter sh, deshalb
#: in einfachen Anführungszeichen.
# shellcheck disable=SC2016
PRUEFEN_SH='cd "$1" && test -s "$2" && zeile="$(awk -v n="$2" "\$2 == n" PRUEFSUMMEN.sha256 | tail -n 1)" && [ -n "$zeile" ] && printf "%s\n" "$zeile" | sha256sum -c --status -'
sicherung_da() {  # $1 = Dateiname
  dc_t 60 exec -T pg-backup sh -c "$PRUEFEN_SH" _ "$SICHERUNGEN" "$1" >/dev/null 2>&1
}

#: Die Sicherung, wie sie vor jeder Migration entsteht (plattform-aufbau.sh
#: kunden_migrieren: backup.sh im Container pg-backup), nur mit Eigentümern
#: und Rechten. -> SICHERUNG_DATEI, SICHERUNG_RECHTE, SICHERUNG_ZEIT
sichern_lauf() {
  local ausgabe rc pfad
  SICHERUNG_DATEI=""; SICHERUNG_RECHTE=0; SICHERUNG_ZEIT=""
  say "Sicherung der Datenbank (pg-backup, verschlüsselt mit dem öffentlichen age-Schlüssel)"
  ausgabe="$(dc_t "$SICHERN_SEK" exec -T -e BACKUP_ART=rueckfall pg-backup /usr/local/bin/backup.sh 2>&1)"
  rc=$?
  [ -z "$ausgabe" ] || printf '%s\n' "$ausgabe" >&2
  [ "$rc" -eq 0 ] || return 1
  pfad="$(printf '%s\n' "$ausgabe" | sed -n 's/^\[pg-backup\] Sicherung startet: //p' | tail -n 1)"
  SICHERUNG_DATEI="${pfad##*/}"
  if [ "$pfad" != "$SICHERUNGEN/$SICHERUNG_DATEI" ] || ! datei_gueltig "$SICHERUNG_DATEI" \
     || ! sicherung_da "$SICHERUNG_DATEI"; then
    SICHERUNG_DATEI=""
    return 1
  fi
  case "$SICHERUNG_DATEI" in
    *-rueckfall.dump.age) SICHERUNG_RECHTE=1 ;;
    *) warn "pg-backup läuft noch mit dem alten backup.sh (ohne Eigentümer und Rechte) — für einen Rückfall nicht einspielbar. Neu bauen: scripts/plattform-aufbau.sh update" ;;
  esac
  SICHERUNG_ZEIT="$(datei_zeit "$SICHERUNG_DATEI")"
  say "Sicherung geschrieben: $SICHERUNG_DATEI"
}

#: Jüngste Sicherung im Volume (jede Art, auch die tägliche) als ISO-Zeit.
neueste_sicherung() {
  local liste name t beste=""
  liste="$(dc_t 15 exec -T pg-backup ls -1 "$SICHERUNGEN" 2>/dev/null)" || return 1
  while IFS= read -r name; do
    name="${name%$'\r'}"
    datei_gueltig "$name" || continue
    t="$(datei_zeit "$name")"
    if [[ "$t" > "$beste" ]]; then beste="$t"; fi
  done <<<"$liste"
  printf '%s' "$beste"
}

#: Entschlüsselt auf den Strom, nie auf die Platte.
sicherung_strom() {  # $1 = Dateiname
  dc exec -T pg-backup cat "$SICHERUNGEN/$1" | age -d -i "$SCHLUESSEL"
}

# --- Schemastand ---------------------------------------------------------------
# Jedes Schema trägt seine eigene alembic_version (ADR-0013 D7). Der Stand
# aller Schemas zusammen sagt, ob ein Update die Datenbank verändert hat;
# gespeichert wird nur seine Prüfsumme (keine Kundennamen im Zustand).
SCHEMA_SQL="SELECT coalesce(string_agg(s || '=' || coalesce(v, '-'), ';' ORDER BY s), '-') FROM (SELECT table_schema AS s, (xpath('/row/v/text()', query_to_xml(format('SELECT string_agg(version_num, %L ORDER BY version_num) AS v FROM %I.alembic_version', ',', table_schema), false, true, '')))[1]::text AS v FROM information_schema.tables WHERE table_name = 'alembic_version') x"
schemastand() {  # -> SHA-256 über den Stand, Exit 1 = nicht lesbar
  local roh
  roh="$(dc_t 20 exec -T postgres psql -X -A -t -q -v ON_ERROR_STOP=1 \
         -U "$PG_USER" -d "$PG_DB" -c "$SCHEMA_SQL" 2>/dev/null)" || return 1
  roh="$(printf '%s' "$roh" | tr -d '\r\n')"
  [ -n "$roh" ] || return 1
  printf '%s' "$roh" | sha256sum | cut -c1-64
}

psql_postgres() {  # $1 = SQL, gegen die Datenbank `postgres`
  dc_t 120 exec -T postgres psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$PG_USER" -d postgres -c "$1"
}

#: Die laufende Datenbank umbenennen statt löschen: sie bleibt als Rückweg
#: liegen (wie „daneben, nie darüber" in sicherung-wiederherstellung.md).
db_beiseite() {  # $1 = neuer Name
  psql_postgres "ALTER DATABASE $(q "$PG_DB") ALLOW_CONNECTIONS false" >/dev/null || return 1
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    psql_postgres "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE datname = '$PG_DB' AND pid <> pg_backend_pid()" >/dev/null 2>&1
    if psql_postgres "ALTER DATABASE $(q "$PG_DB") RENAME TO $(q "$1")" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  psql_postgres "ALTER DATABASE $(q "$PG_DB") ALLOW_CONNECTIONS true" >/dev/null 2>&1
  return 1
}

#: Datenbank aus der Sicherung einspielen. -> 0 = eingespielt (magister-api
#: bleibt angehalten, bis plattform-aufbau.sh update sie startet);
#: DATEN_BEISEITE (Name der bisherigen), DATEN_UNVERAENDERT (1 = die
#: bisherige ist an ihrem Platz und magister-api läuft wieder), DATEN_FEHLER
#: (Satz für die Meldung).
daten_einspielen() {  # $1 = Dateiname
  local datei="$1" beiseite
  DATEN_BEISEITE=""; DATEN_UNVERAENDERT=1; DATEN_FEHLER=""
  say "Probelauf: $datei entschlüsseln und ganz lesen (es wird nichts eingespielt)"
  if ! sicherung_strom "$datei" | dc exec -T postgres pg_restore -f /dev/null; then
    DATEN_FEHLER="Sicherung nicht lesbar"
    return 1
  fi
  say "magister-api anhalten, damit niemand schreibt"
  dc_t 120 stop magister-api || warn "magister-api liess sich nicht anhalten"
  beiseite="${PG_DB}_vor_rueckfall_$(date -u +%Y%m%dt%H%M%Sz)"
  say "Bisherige Datenbank beiseitelegen: $beiseite (wird nicht gelöscht)"
  if ! db_beiseite "$beiseite"; then
    DATEN_FEHLER="bisherige Datenbank nicht beiseitezulegen"
    dc_t 120 start magister-api || warn "magister-api liess sich nicht starten"
    return 1
  fi
  DATEN_UNVERAENDERT=0
  say "Datenbank aus $datei einspielen"
  if sicherung_strom "$datei" \
     | dc exec -T postgres pg_restore --create --exit-on-error -U "$PG_USER" -d postgres; then
    DATEN_BEISEITE="$beiseite"
    return 0
  fi
  warn "Einspielen gescheitert — die bisherige Datenbank kommt an ihren Platz zurück"
  # Gelöscht wird nur, was eben selbst halb eingespielt wurde: der Name ist
  # erst seit dem Umbenennen oben wieder frei.
  if psql_postgres "DROP DATABASE IF EXISTS $(q "$PG_DB") WITH (FORCE)" >/dev/null \
     && psql_postgres "ALTER DATABASE $(q "$beiseite") RENAME TO $(q "$PG_DB")" >/dev/null \
     && psql_postgres "ALTER DATABASE $(q "$PG_DB") ALLOW_CONNECTIONS true" >/dev/null; then
    DATEN_UNVERAENDERT=1
    DATEN_FEHLER="Einspielen gescheitert, bisherige wieder an ihrem Platz"
    dc_t 120 start magister-api || warn "magister-api liess sich nicht starten"
  else
    DATEN_FEHLER="Einspielen gescheitert, bisherige liegt als $beiseite"
  fi
  return 1
}

# --- Zustand -------------------------------------------------------------------
# plattform/betrieb/zustand (root, 0600), Zeilen schluessel=wert, gelesen und
# nicht ausgeführt. Keine Geheimnisse: Commits, Zeiten, ein Dateiname, eine
# Prüfsumme.
z_lesen() {
  Z_VORHER_COMMIT=""; Z_VORHER_REF=""; Z_VORHER_VERSION=""; Z_VORHER_ZEIT=""
  Z_VORHER_SICHERUNG=""; Z_VORHER_RECHTE=0; Z_VORHER_SCHEMA=""; Z_ZURUECK_OFFEN=0
  Z_LETZTE_SICHERUNG=""
  [ -f "$ZUSTAND" ] || return 0
  local k v
  while IFS='=' read -r k v; do
    case "$k" in
      vorher_commit)    [[ "$v" =~ ^[0-9a-f]{40}$ ]] && Z_VORHER_COMMIT="$v" ;;
      vorher_ref)       ref_gueltig "$v" && Z_VORHER_REF="$v" ;;
      vorher_version)   [[ "$v" =~ ^[A-Za-z0-9._+/-]{1,64}$ ]] && Z_VORHER_VERSION="$v" ;;
      vorher_zeit)      iso_gueltig "$v" && Z_VORHER_ZEIT="$v" ;;
      vorher_sicherung) datei_gueltig "$v" && Z_VORHER_SICHERUNG="$v" ;;
      vorher_rechte)    [ "$v" = 1 ] && Z_VORHER_RECHTE=1 ;;
      vorher_schema)    [[ "$v" =~ ^[0-9a-f]{64}$ ]] && Z_VORHER_SCHEMA="$v" ;;
      zurueck_offen)    [ "$v" = 1 ] && Z_ZURUECK_OFFEN=1 ;;
      letzte_sicherung) iso_gueltig "$v" && Z_LETZTE_SICHERUNG="$v" ;;
    esac
  done <"$ZUSTAND"
  return 0
}

z_schreiben() {
  mkdir -p "$ZUSTAND_DIR" && chmod 700 "$ZUSTAND_DIR" || return 1
  (
    umask 077
    cat >"$ZUSTAND.tmp" <<EOF
# Zustand von scripts/betrieb.sh (ADR-0028). Keine Geheimnisse.
vorher_commit=$Z_VORHER_COMMIT
vorher_ref=$Z_VORHER_REF
vorher_version=$Z_VORHER_VERSION
vorher_zeit=$Z_VORHER_ZEIT
vorher_sicherung=$Z_VORHER_SICHERUNG
vorher_rechte=$Z_VORHER_RECHTE
vorher_schema=$Z_VORHER_SCHEMA
zurueck_offen=$Z_ZURUECK_OFFEN
letzte_sicherung=$Z_LETZTE_SICHERUNG
EOF
  ) && mv -f "$ZUSTAND.tmp" "$ZUSTAND"
}

#: Lässt sich die Datenbank auf den Stand vor dem Update bringen?
#: DATEN_NOETIG: 1 = der Schemastand ist seither ein anderer (oder unlesbar).
#: DATEN_MOEGLICH: 1 = die Sicherung lässt sich hier automatisch einspielen.
#: DATEN_GRUND/DATEN_SCHRITT: warum nicht, und was dann von Hand zu tun ist.
daten_pruefen() {
  local jetzt=""
  DATEN_NOETIG=1; DATEN_MOEGLICH=0; DATEN_GRUND=""; DATEN_SCHRITT=""
  jetzt="$(schemastand)" || jetzt=""
  if [ -n "$jetzt" ] && [ "$jetzt" = "$Z_VORHER_SCHEMA" ]; then DATEN_NOETIG=0; fi
  local runbook="Wiederherstellung nach docs/runbooks/sicherung-wiederherstellung.md"
  if [ -z "$Z_VORHER_SICHERUNG" ]; then
    DATEN_GRUND="keine Sicherung zum Update"; DATEN_SCHRITT="$runbook"
  elif [ "$Z_VORHER_RECHTE" != 1 ]; then
    DATEN_GRUND="die Sicherung hat keine Eigentümer und Rechte"; DATEN_SCHRITT="$runbook"
  elif [ ! -f "$SCHLUESSEL" ]; then
    DATEN_GRUND="der private Sicherungsschlüssel fehlt auf dem Host"
    DATEN_SCHRITT="Schlüssel nach plattform/certs/backup-age.key legen, dann zurueck"
  elif ! command -v age >/dev/null 2>&1; then
    DATEN_GRUND="age fehlt auf dem Host"; DATEN_SCHRITT="age installieren, dann zurueck"
  elif ! sicherung_da "$Z_VORHER_SICHERUNG"; then
    DATEN_GRUND="die Sicherung fehlt oder ihre Prüfsumme stimmt nicht"; DATEN_SCHRITT="$runbook"
  else
    DATEN_MOEGLICH=1
  fi
}

zurueck_moeglich_pruefen() {
  ZURUECK_MOEGLICH=false
  if [ "$Z_ZURUECK_OFFEN" != 1 ] || [ -z "$Z_VORHER_COMMIT" ]; then return 0; fi
  git_r cat-file -e "$Z_VORHER_COMMIT^{commit}" 2>/dev/null || return 0
  daten_pruefen
  if [ "$DATEN_MOEGLICH" = 1 ] || [ "$DATEN_NOETIG" = 0 ]; then ZURUECK_MOEGLICH=true; fi
  return 0
}

# --- Antwort (stdout, eine Zeile) ------------------------------------------------
AKTION="unbekannt"
GESUND=""            # true/false, leer = nicht geprüft
GESUND_GRUND=""
ZURUECK_MOEGLICH=""  # true/false, leer = nicht geprüft
DATEN_BEISEITE=""; DATEN_UNVERAENDERT=1; DATEN_FEHLER=""

json_text() {  # $1 -> JSON-Zeichenkette, leer -> null
  if [ -z "${1:-}" ]; then printf 'null'; return 0; fi
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="$(printf '%s' "$s" | tr -d '\000-\037\177')"
  printf '"%s"' "$s"
}
json_bool() { case "${1:-}" in true|false) printf '%s' "$1" ;; *) printf 'null' ;; esac; }
kuerzen() { local LC_ALL=C.UTF-8; printf '%s' "${1:0:300}"; }

#: Herkunft des Checkouts: angehängter Branch bzw. losgelöst. Das Cockpit nimmt
#: den Branch als Vorgabe seiner Quelle (statt main). Ein Branch mit ungültigem
#: Namen: null, aber nicht losgelöst; ohne git-Checkout wie losgelöst.
herkunft_erheben() {
  local b
  S_BRANCH=""; S_LOSGELOEST=true
  if b="$(git_r symbolic-ref -q --short HEAD 2>/dev/null)" && [ -n "$b" ]; then
    S_LOSGELOEST=false
    if ref_gueltig "$b"; then S_BRANCH="$b"; fi
  fi
}

stand_erheben() {  # $1 = Exit-Code
  S_COMMIT="$(git_r rev-parse -q --verify HEAD 2>/dev/null)"
  [[ "$S_COMMIT" =~ ^[0-9a-f]{40}$ ]] || S_COMMIT=""
  herkunft_erheben
  S_VERSION=""
  [ -z "$S_COMMIT" ] || S_VERSION="$(version_von "$S_COMMIT")"
  [[ "$S_VERSION" =~ ^[A-Za-z0-9._+/-]{1,64}$ ]] || S_VERSION=""
  z_lesen
  S_VORHER="null"
  if [ -n "$Z_VORHER_COMMIT" ]; then
    S_VORHER="{\"version\":$(json_text "$Z_VORHER_VERSION"),\"commit\":$(json_text "$Z_VORHER_COMMIT"),\"zeit\":$(json_text "$Z_VORHER_ZEIT")}"
  fi
  S_LETZTE="$Z_LETZTE_SICHERUNG"
  # Belegt: eine andere Aktion läuft — nichts prüfen, nur sagen, was feststeht.
  [ "$1" -ne 4 ] || return 0
  if ! docker_da; then
    [ -n "$GESUND" ] || GESUND=false
    return 0
  fi
  if [ -z "$GESUND" ]; then
    if gesund_einmal; then GESUND=true; else GESUND=false; fi
  fi
  local neueste
  if neueste="$(neueste_sicherung)" && [[ "$neueste" > "$S_LETZTE" ]]; then S_LETZTE="$neueste"; fi
  [ -n "$ZURUECK_MOEGLICH" ] || zurueck_moeglich_pruefen
}

antwort() {  # $1 = Exit-Code, $2 = Meldung (fester Text, keine fremden Ausgaben)
  local code="$1" ok=false m
  [ "$code" -eq 0 ] && ok=true
  m="$(kuerzen "$2")"
  stand_erheben "$code"
  printf '{"format":"betrieb/v1","produkt":"magister","aktion":%s,"ok":%s,"meldung":%s,"stand":{"version":%s,"commit":%s,"quelle":"git","kanal":null,"gesund":%s,"zurueck_moeglich":%s,"vorher":%s,"letzte_sicherung":%s,"herkunft":{"branch":%s,"losgeloest":%s}}}\n' \
    "$(json_text "$AKTION")" "$ok" "$(json_text "$m")" \
    "$(json_text "$S_VERSION")" "$(json_text "$S_COMMIT")" \
    "$(json_bool "$GESUND")" "$(json_bool "$ZURUECK_MOEGLICH")" "$S_VORHER" \
    "$(json_text "$S_LETZTE")" "$(json_text "$S_BRANCH")" "$(json_bool "$S_LOSGELOEST")" >&3
  say "Ende (Exit $code): $m"
  exit "$code"
}

sperren() {
  if ! exec 9>>"$SPERRE"; then
    antwort 3 "Abgelehnt: Sperre $SPERRE lässt sich nicht anlegen. Nichts geändert."
  fi
  flock -n 9 || antwort 4 "Belegt: auf diesem Checkout läuft schon eine Aktion."
}

# --- Aktionen ------------------------------------------------------------------
cmd_stand() {
  local commit branch version
  commit="$(git_r rev-parse -q --verify HEAD 2>/dev/null)" \
    || antwort 0 "Kein git-Checkout in $REPO – Version unbekannt."
  branch="$(git_r symbolic-ref -q --short HEAD 2>/dev/null)" || branch="losgelöst"
  ref_gueltig "$branch" || branch="losgelöst"
  version="$(version_von "$commit")"
  if docker_da && gesund_einmal; then
    GESUND=true
    antwort 0 "Stand $version ($branch), Health ok"
  fi
  GESUND=false
  antwort 0 "Stand $version ($branch), Health nicht ok: ${GESUND_GRUND:-Docker antwortet nicht}"
}

cmd_sichern() {
  if ! sichern_lauf; then
    antwort 2 "Sicherung gescheitert (Ausgabe von pg-backup im Journal des Agenten). Nächster Schritt: scripts/plattform-aufbau.sh status – läuft pg-backup?"
  fi
  z_lesen
  Z_LETZTE_SICHERUNG="$SICHERUNG_ZEIT"
  z_schreiben || warn "Zustand nicht geschrieben: $ZUSTAND"
  if [ "$SICHERUNG_RECHTE" = 1 ]; then
    antwort 0 "Sicherung $SICHERUNG_DATEI geschrieben (verschlüsselt)"
  fi
  antwort 0 "Sicherung $SICHERUNG_DATEI geschrieben (verschlüsselt, ohne Eigentümer und Rechte: pg-backup ist alt – scripts/plattform-aufbau.sh update baut ihn neu)"
}

cmd_neustart() {
  say "Datenebene neu starten (ohne Neubau, ohne neue Images; die Konsole bleibt)"
  if ! dc_t 300 restart; then
    antwort 2 "Neustart gescheitert (docker compose restart, Journal des Agenten). Nächster Schritt: scripts/plattform-aufbau.sh status"
  fi
  if gesund_warten "$HEALTH_SEK"; then
    antwort 0 "Datenebene neu gestartet, Health ok"
  fi
  antwort 2 "Datenebene neu gestartet, Health nach $HEALTH_SEK s nicht ok ($GESUND_GRUND). Nächster Schritt: scripts/plattform-aufbau.sh status"
}

cmd_aktualisieren() {  # $1 = Ref, $2 = Bundle (leer = von origin), $3 = Commit
  local ref="$1" bundle="${2:-}" commit="${3:-}" herkunft upstream=""
  local alt_commit alt_branch alt_version neu_version n schema_vorher alter_zustand=""
  local hatte_zustand=0 grund
  alt_commit="$(git_r rev-parse -q --verify HEAD 2>/dev/null)" \
    || antwort 3 "Abgelehnt: $REPO ist kein git-Checkout. Nichts geändert."
  alt_branch="$(git_r symbolic-ref -q --short HEAD 2>/dev/null)" || alt_branch=""
  ref_gueltig "$alt_branch" || alt_branch=""
  alt_version="$(version_von "$alt_commit")"

  n="$(lokale_aenderungen)" || antwort 3 "Abgelehnt: git status gescheitert. Nichts geändert."
  [ "$n" -eq 0 ] \
    || antwort 3 "Abgelehnt: $n lokale Änderung(en) an versionierten Dateien im Checkout (git status). Nichts geändert."

  if [ -n "$bundle" ]; then
    say "Neuen Stand aus dem Bundle des Cockpits holen (${commit:0:12}, ohne origin)"
    bundle_holen "$bundle" "$commit" || antwort 3 "Abgelehnt: $BUNDLE_FEHLER. Nichts geändert."
    ZIEL_COMMIT="$commit"
    ZIEL_BRANCH="$(bundle_branch "$ref" "$commit")"
    herkunft="der Stand aus dem Cockpit"; upstream="ohne-upstream"
  else
    say "Neuen Stand holen (git fetch origin)"
    timeout 180 git -c safe.directory="$REPO" -C "$REPO" fetch --quiet --prune --tags --force origin \
      || antwort 3 "Abgelehnt: git fetch von origin gescheitert (Netz oder Zugang des Hosts; Repo privat: Code als Bundle aus dem Cockpit, Host-Agent aktualisieren). Nichts geändert."
    ref_aufloesen "$ref" \
      || antwort 3 "Abgelehnt: $ref ist weder Branch auf origin noch Tag noch Commit. Nichts geändert."
    herkunft="origin/$ZIEL_BRANCH"
  fi
  neu_version="$(version_von "$ZIEL_COMMIT")"

  if [ "$ZIEL_COMMIT" = "$alt_commit" ]; then
    antwort 0 "schon auf $alt_version"
  fi
  if git_r merge-base --is-ancestor "$ZIEL_COMMIT" "$alt_commit" 2>/dev/null; then
    [ "$neu_version" = "$ref" ] || ref="$ref ($neu_version)"
    antwort 3 "Abgelehnt: $ref ist älter als der laufende Stand $alt_version – zurück nur über zurueck. Nichts geändert."
  fi
  if [ -n "$ZIEL_BRANCH" ] && git_r rev-parse -q --verify "refs/heads/$ZIEL_BRANCH" >/dev/null 2>&1 \
     && ! git_r merge-base --is-ancestor "refs/heads/$ZIEL_BRANCH" "$ZIEL_COMMIT" 2>/dev/null; then
    antwort 3 "Abgelehnt: der lokale Branch $ZIEL_BRANCH hat Commits, die $herkunft nicht hat. Nichts geändert."
  fi
  # Nur Nachfahren des laufenden Stands: eine andere Linie (anderer Branch, umgeschrieben) nie,
  # auch nicht mit neuerer Version. Nur mit Objekten im Repo – mit Bundle nie origin.
  local linie=0
  git_r merge-base --is-ancestor "$alt_commit" "$ZIEL_COMMIT" </dev/null 2>/dev/null || linie=$?
  case "$linie" in
    0) ;;
    1) antwort 3 "Abgelehnt: $ref liegt auf einer anderen Linie als der laufende Stand $alt_version (${alt_branch:-losgelöst}) – nichts geändert" ;;
    *) antwort 3 "Abgelehnt: Abstammung von $ref gegenüber dem laufenden Stand $alt_version nicht prüfbar (git merge-base) – nichts geändert" ;;
  esac

  schema_vorher="$(schemastand)" || { schema_vorher=""; warn "Schemastand vor dem Update nicht lesbar"; }
  sichern_lauf \
    || antwort 3 "Abgelehnt: Sicherung vor dem Update gescheitert (Ausgabe von pg-backup im Journal). Nichts geändert."

  # Der Zustand für `zurueck` steht VOR dem Umschalten: wird dieser Lauf
  # abgebrochen (Zeitlimit des Agenten), geht `zurueck` trotzdem.
  if [ -f "$ZUSTAND" ]; then alter_zustand="$(cat "$ZUSTAND")"; hatte_zustand=1; fi
  Z_VORHER_COMMIT="$alt_commit"; Z_VORHER_REF="$alt_branch"; Z_VORHER_VERSION="$alt_version"
  Z_VORHER_ZEIT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; Z_VORHER_SICHERUNG="$SICHERUNG_DATEI"
  Z_VORHER_RECHTE="$SICHERUNG_RECHTE"; Z_VORHER_SCHEMA="$schema_vorher"; Z_ZURUECK_OFFEN=1
  Z_LETZTE_SICHERUNG="$SICHERUNG_ZEIT"
  z_schreiben || antwort 3 "Abgelehnt: Zustand $ZUSTAND lässt sich nicht schreiben. Nichts geändert."

  say "Umschalten: $alt_version → $neu_version (${ZIEL_BRANCH:-losgelöst})"
  if ! umschalten "$ZIEL_COMMIT" "$ZIEL_BRANCH" "$upstream"; then
    if [ "$(git_r rev-parse HEAD 2>/dev/null)" = "$alt_commit" ]; then
      zustand_zurueck "$hatte_zustand" "$alter_zustand"
      antwort 3 "Abgelehnt: git checkout von $ref gescheitert (Journal des Agenten). Nichts geändert."
    fi
    rueckfall "$alt_commit" "$alt_branch" "$alt_version" "$neu_version" \
      "Umschalten gescheitert" "$hatte_zustand" "$alter_zustand"
  fi

  if ! aufbau "$UPDATE_SEK" update; then
    grund="plattform-aufbau.sh update gescheitert"
  elif ! gesund_warten "$HEALTH_SEK"; then
    grund="Health nach $HEALTH_SEK s nicht ok: $GESUND_GRUND"
  else
    antwort 0 "$alt_version → $neu_version, Health ok"
  fi
  rueckfall "$alt_commit" "$alt_branch" "$alt_version" "$neu_version" "$grund" \
    "$hatte_zustand" "$alter_zustand"
}

#: Den Zustand von vor einem gescheiterten Versuch zurücklegen: der Versuch
#: zählt nicht als „letztes erfolgreiches Update". Die neue Sicherung bleibt
#: die letzte.
zustand_zurueck() {  # $1 = 1, wenn es vorher einen gab, $2 = Inhalt
  local letzte="$Z_LETZTE_SICHERUNG"
  if [ "$1" = 1 ]; then
    ( umask 077; printf '%s\n' "$2" >"$ZUSTAND.tmp" ) && mv -f "$ZUSTAND.tmp" "$ZUSTAND"
  else
    rm -f "$ZUSTAND"
  fi
  z_lesen
  Z_LETZTE_SICHERUNG="$letzte"
  z_schreiben || warn "Zustand nicht geschrieben: $ZUSTAND"
}

#: Selbst zurück nach einem gescheiterten Update. Endet immer mit `antwort`.
#: Erst die Datenbank, dann der Code: scheitert das Einspielen, passen Code
#: und Datenbank wenigstens noch zueinander.
rueckfall() {  # $1 alter Commit, $2 alter Branch, $3 alte Version, $4 neue Version, $5 Grund, $6/$7 Zustand
  local alt_commit="$1" alt_branch="$2" av="$3" nv="$4" grund="$5" daten
  warn "Update gescheitert ($grund) — Rückfall auf $av"
  daten_pruefen
  if [ "$DATEN_NOETIG" = 1 ] && [ "$DATEN_MOEGLICH" != 1 ]; then
    antwort 2 "Update auf $nv gescheitert, kein Rückfall: Schemastand geändert und $DATEN_GRUND. Nächster Schritt: $DATEN_SCHRITT. Grund: $grund."
  fi
  if [ "$DATEN_MOEGLICH" = 1 ]; then
    if daten_einspielen "$Z_VORHER_SICHERUNG"; then
      daten="Datenbank aus der Sicherung (bisherige als $DATEN_BEISEITE behalten)"
    elif [ "$DATEN_UNVERAENDERT" = 1 ] && [ "$DATEN_NOETIG" = 0 ]; then
      daten="Datenbank unverändert ($DATEN_FEHLER, Schemastand gleich)"
    elif [ "$DATEN_UNVERAENDERT" = 1 ]; then
      antwort 2 "Update auf $nv gescheitert, kein Rückfall: $DATEN_FEHLER, läuft weiter auf $nv. Nächster Schritt: Wiederherstellung nach docs/runbooks/sicherung-wiederherstellung.md. Grund: $grund."
    else
      antwort 2 "Update auf $nv gescheitert, Rückfall: $DATEN_FEHLER, magister-api angehalten. Nächster Schritt: Wiederherstellung nach docs/runbooks/sicherung-wiederherstellung.md. Grund: $grund."
    fi
  else
    daten="Datenbank unverändert (Schemastand gleich; $DATEN_GRUND)"
  fi
  if ! umschalten "$alt_commit" "$alt_branch"; then
    antwort 2 "Update auf $nv gescheitert, Rückfall: git checkout gescheitert. Nächster Schritt: git checkout ${alt_commit:0:12}, dann scripts/plattform-aufbau.sh update. Grund: $grund."
  fi
  if ! aufbau "$RUECKFALL_SEK" update; then
    antwort 2 "Update auf $nv gescheitert, zurück auf $av, aber plattform-aufbau.sh update gescheitert. Nächster Schritt: scripts/plattform-aufbau.sh update. Grund: $grund."
  fi
  if ! gesund_warten "$RUECKFALL_HEALTH_SEK"; then
    antwort 2 "Update auf $nv gescheitert, zurück auf $av, Health weiterhin nicht ok ($GESUND_GRUND). Nächster Schritt: scripts/plattform-aufbau.sh status. Grund: $grund."
  fi
  zustand_zurueck "$6" "$7"
  ZURUECK_MOEGLICH=""
  antwort 1 "$av → $nv gescheitert ($grund); zurück auf $av, $daten, Health ok"
}

cmd_zurueck() {
  local jetzt_commit jetzt_version vv daten
  z_lesen
  if [ "$Z_ZURUECK_OFFEN" != 1 ] || [ -z "$Z_VORHER_COMMIT" ]; then
    antwort 3 "Abgelehnt: kein Zurück möglich – kein Update aus dem Cockpit oder schon zurück. Nichts geändert."
  fi
  vv="${Z_VORHER_VERSION:-${Z_VORHER_COMMIT:0:12}}"
  git_r cat-file -e "$Z_VORHER_COMMIT^{commit}" 2>/dev/null \
    || antwort 3 "Abgelehnt: der Stand $vv liegt nicht mehr im Checkout. Nichts geändert."
  local n
  n="$(lokale_aenderungen)" || antwort 3 "Abgelehnt: git status gescheitert. Nichts geändert."
  [ "$n" -eq 0 ] \
    || antwort 3 "Abgelehnt: $n lokale Änderung(en) an versionierten Dateien im Checkout (git status). Nichts geändert."
  daten_pruefen
  if [ "$DATEN_NOETIG" = 1 ] && [ "$DATEN_MOEGLICH" != 1 ]; then
    antwort 3 "Abgelehnt: zurück auf $vv braucht die Datenbank (Schemastand geändert), aber $DATEN_GRUND. Nichts geändert. Nächster Schritt: $DATEN_SCHRITT."
  fi
  jetzt_commit="$(git_r rev-parse HEAD 2>/dev/null)"
  jetzt_version="$(version_von "$jetzt_commit")"

  say "Zurück: $jetzt_version → $vv"
  if [ "$DATEN_MOEGLICH" = 1 ]; then
    if daten_einspielen "$Z_VORHER_SICHERUNG"; then
      daten="Datenbank aus der Sicherung vom Update (bisherige als $DATEN_BEISEITE behalten)"
    elif [ "$DATEN_UNVERAENDERT" = 1 ] && [ "$DATEN_NOETIG" = 0 ]; then
      daten="Datenbank unverändert ($DATEN_FEHLER, Schemastand gleich)"
    elif [ "$DATEN_UNVERAENDERT" = 1 ]; then
      antwort 2 "Zurück auf $vv gescheitert: $DATEN_FEHLER, läuft weiter auf $jetzt_version. Nächster Schritt: Wiederherstellung nach docs/runbooks/sicherung-wiederherstellung.md."
    else
      antwort 2 "Zurück auf $vv gescheitert: $DATEN_FEHLER, magister-api angehalten. Nächster Schritt: Wiederherstellung nach docs/runbooks/sicherung-wiederherstellung.md."
    fi
  else
    daten="Datenbank unverändert (Schemastand gleich; $DATEN_GRUND)"
  fi
  if ! umschalten "$Z_VORHER_COMMIT" "$Z_VORHER_REF"; then
    if [ "$(git_r rev-parse HEAD 2>/dev/null)" = "$jetzt_commit" ] && [ -z "$DATEN_BEISEITE" ]; then
      antwort 3 "Abgelehnt: git checkout auf $vv gescheitert (Journal des Agenten). Nichts geändert."
    fi
    antwort 2 "Zurück auf $vv: git checkout gescheitert. Nächster Schritt: git checkout ${Z_VORHER_COMMIT:0:12}, dann scripts/plattform-aufbau.sh update."
  fi
  if ! aufbau "$UPDATE_SEK" update; then
    antwort 2 "Zurück auf $vv: plattform-aufbau.sh update gescheitert. Nächster Schritt: scripts/plattform-aufbau.sh update."
  fi
  if ! gesund_warten "$HEALTH_SEK"; then
    antwort 2 "Zurück auf $vv: Health nach $HEALTH_SEK s nicht ok ($GESUND_GRUND). Nächster Schritt: scripts/plattform-aufbau.sh status."
  fi
  z_lesen
  Z_ZURUECK_OFFEN=0
  z_schreiben || warn "Zustand nicht geschrieben: $ZUSTAND"
  ZURUECK_MOEGLICH=false
  antwort 0 "$jetzt_version → $vv zurück, $daten, Health ok"
}

# --- Aufruf --------------------------------------------------------------------
#: aktualisieren --ref <ref> [--bundle <datei> --commit <sha>] -> A_REF,
#: A_BUNDLE (absolut, leer = von origin), A_COMMIT. Jede Angabe höchstens einmal.
angaben_lesen() {
  local gesehen=" " aufruf="Abgelehnt: Magister wird aus git aktualisiert – aktualisieren --ref <git-ref> [--bundle <datei> --commit <sha>]. Nichts geändert."
  A_REF=""; A_BUNDLE=""; A_COMMIT=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --ref|--bundle|--commit)
        [ $# -ge 2 ] || antwort 3 "$aufruf"
        case "$gesehen" in *" $1 "*) antwort 3 "$aufruf" ;; esac
        gesehen="$gesehen$1 " ;;
      *) antwort 3 "$aufruf" ;;
    esac
    case "$1" in
      --ref)    A_REF="$2" ;;
      --bundle) A_BUNDLE="$2" ;;
      --commit) A_COMMIT="$2" ;;
    esac
    shift 2
  done
  case "$gesehen" in *" --ref "*) ;; *) antwort 3 "$aufruf" ;; esac
  if ! ref_gueltig "$A_REF" || [ "$A_REF" = "HEAD" ]; then
    antwort 3 "Abgelehnt: ungültige Ref – erlaubt sind Branch, Tag oder Commit (Buchstaben, Ziffern, . _ / -, ohne ..). Nichts geändert."
  fi
  local mit_bundle=0 mit_commit=0
  case "$gesehen" in *" --bundle "*) mit_bundle=1 ;; esac
  case "$gesehen" in *" --commit "*) mit_commit=1 ;; esac
  [ "$mit_bundle" = "$mit_commit" ] \
    || antwort 3 "Abgelehnt: --bundle und --commit nur zusammen. Nichts geändert."
  [ "$mit_bundle" = 1 ] || return 0
  [[ "$A_COMMIT" =~ ^[0-9a-f]{40}$ ]] \
    || antwort 3 "Abgelehnt: --commit ist kein Commit (40 Zeichen 0-9, a-f). Nichts geändert."
  A_BUNDLE="$(bundle_datei "$A_BUNDLE")" \
    || antwort 3 "Abgelehnt: Bundle fehlt bzw. ist leer. Nichts geändert."
}

# Alles steht in Funktionen, und diese Datei wird erst ganz gelesen, bevor
# etwas läuft: `aktualisieren` tauscht sie im Checkout aus, während sie läuft.
main() {
  local aktion="${1:-}"
  [ $# -eq 0 ] || shift
  if [[ "$aktion" =~ ^[a-z]{1,20}$ ]]; then AKTION="$aktion"; fi
  case "$aktion" in
    stand|sichern|zurueck|neustart)
      [ $# -eq 0 ] || antwort 3 "Abgelehnt: $aktion nimmt keine Argumente. Nichts geändert." ;;
    aktualisieren)
      angaben_lesen "$@" ;;
    *)
      AKTION="${AKTION:-unbekannt}"
      antwort 3 "Abgelehnt: unbekannte Aktion – erlaubt: stand, sichern, aktualisieren, zurueck, neustart. Nichts geändert." ;;
  esac
  sperren
  say "$aktion $* (Checkout $REPO)"
  case "$aktion" in
    stand)         cmd_stand ;;
    sichern)       cmd_sichern ;;
    aktualisieren) cmd_aktualisieren "$A_REF" "$A_BUNDLE" "$A_COMMIT" ;;
    zurueck)       cmd_zurueck ;;
    neustart)      cmd_neustart ;;
  esac
}

main "$@"; exit $?
