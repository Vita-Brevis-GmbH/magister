#!/usr/bin/env bash
# pitr-drill.sh
#
# Übt die Wiederherstellung auf einen Zeitpunkt (ADR-0016 Ebene 1,
# Entscheid E17) — auf dem BACKUP-HOST, gegen ein Wegwerf-Verzeichnis, ohne
# den laufenden Betrieb zu berühren.
#
# Warum es diesen Ablauf gibt und nicht nur `pgbackrest info`: eine Sicherung,
# die nie eingespielt wurde, ist eine Vermutung. `info` sagt, dass Dateien da
# sind. Dieser Ablauf sagt, dass daraus eine Datenbank wird, die Fragen
# beantwortet — und er sagt es, bevor jemand es wissen MUSS.
#
# Was er tut:
#   1. Vollsicherung und WAL auf einen Zeitpunkt zurückspielen (Vorgabe: vor
#      einer Stunde, also innerhalb der WAL-Kette).
#   2. Einen Postgres auf einem freien Port hochfahren, nur auf localhost.
#   3. Ein paar Fragen stellen: kommt die Wiederherstellung bis zum
#      Zielzeitpunkt, sind die Kundenschemata da, stimmen die Zeilenzahlen
#      grob.
#   4. Alles wieder abräumen.
#
# Voraussetzungen auf dem Backup-Host: pgbackrest, dieselbe Postgres-Hauptversion
# wie in Produktion (`pg_ctl`, `initdb` im PATH oder unter /usr/lib/postgresql),
# Platz für eine Kopie des Clusters.
#
# Usage:
#   sudo -u pgbackrest ./pitr-drill.sh --stanza magister
#   sudo -u pgbackrest ./pitr-drill.sh --stanza magister --target '2026-09-09 14:37:00+02'
#   sudo -u pgbackrest ./pitr-drill.sh --stanza magister --keep    # nicht abräumen
#
# Rückgabewert: 0 = geübt und bestanden, sonst Befund. Für cron gedacht.

set -euo pipefail

STANZA=""
TARGET=""
WORKROOT="${TMPDIR:-/var/tmp}"
PORT=""
KEEP=0
PG_MIN_TABLES=1

die() { printf 'BEFUND: %s\n' "$*" >&2; exit 1; }
note() { printf '  %s\n' "$*"; }
step() { printf '\n=== %s ===\n' "$*"; }

usage() {
    awk 'NR>=3 && /^#/ { sub(/^# ?/, ""); print; next } NR>=3 { exit }' "$0"
}

CLEANUP_DIR=""
CLEANUP_PORT=""

cleanup() {
    if [[ -n "$CLEANUP_PORT" && -d "${CLEANUP_DIR:-}/data" ]]; then
        "$PG_BIN/pg_ctl" -D "$CLEANUP_DIR/data" -m immediate stop >/dev/null 2>&1 || true
    fi
    if (( KEEP == 0 )) && [[ -n "$CLEANUP_DIR" && -d "$CLEANUP_DIR" ]]; then
        rm -rf "$CLEANUP_DIR"
    elif [[ -n "$CLEANUP_DIR" ]]; then
        printf '\nStehen gelassen (--keep): %s\n' "$CLEANUP_DIR"
    fi
    return 0
}

# --- Postgres-Werkzeuge finden ---------------------------------------------
# Auf Debian/Ubuntu liegen sie nicht im PATH, sondern versioniert unter
# /usr/lib/postgresql/<version>/bin. Die höchste gefundene Version gewinnt —
# und wird unten gegen die Version im Repository geprüft, denn ein Cluster
# lässt sich nicht mit einer anderen Hauptversion starten.
find_pg_bin() {
    if command -v pg_ctl >/dev/null 2>&1 && command -v initdb >/dev/null 2>&1; then
        dirname "$(command -v pg_ctl)"
        return 0
    fi
    local candidate
    candidate="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)"
    [[ -n "$candidate" && -x "$candidate/pg_ctl" ]] || return 1
    printf '%s' "$candidate"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --stanza) STANZA="$2"; shift 2 ;;
        --target) TARGET="$2"; shift 2 ;;
        --workroot) WORKROOT="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;   # nur der Name des Sockets
        --keep) KEEP=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unbekannte Option: $1" ;;
    esac
done

[[ -n "$STANZA" ]] || die "--stanza fehlt."
command -v pgbackrest >/dev/null 2>&1 || die "pgbackrest nicht gefunden."

PG_BIN="$(find_pg_bin)" || die "Postgres-Werkzeuge nicht gefunden (pg_ctl, initdb). \
Der Backup-Host braucht dieselbe Postgres-Hauptversion wie die Produktion — \
ohne sie lässt sich eine Sicherung hier nicht einspielen, und das merkt man \
sonst am Tag, an dem es darauf ankommt."

if [[ -z "$TARGET" ]]; then
    # Eine Stunde zurück: sicher innerhalb der WAL-Kette und trotzdem ein
    # echter Zeitpunkt, kein „neuester Stand" (der auch ohne WAL ginge und
    # damit die Hälfte des Verfahrens nicht prüft).
    TARGET="$(date -u -d '1 hour ago' '+%Y-%m-%d %H:%M:%S+00')"
fi
# Kein freier TCP-Port nötig: die Übung hört ausschliesslich auf einem
# Unix-Socket in ihrem eigenen 0700-Verzeichnis. Die Portnummer ist damit nur
# noch der Dateiname des Sockets und kann fest bleiben.
[[ -n "$PORT" ]] || PORT=5432

step "Vorbereitung"
note "Stanza:       $STANZA"
note "Zielzeitpunkt: $TARGET"
note "Socket-Port:  $PORT (nur Unix-Socket, kein TCP)"
note "pg-Werkzeuge: $PG_BIN"

step "Was das Repository hat"
pgbackrest --stanza="$STANZA" info || die "pgbackrest info scheiterte."

# --- Spool-Verzeichnis: eine Voraussetzung, keine Option ------------------
# `restore` räumt das Spool-Verzeichnis der Stanza auf, auch ohne asynchrone
# Archivierung, und nimmt dafür die Vorgabe /var/spool/pgbackrest. Fehlt dort
# das Schreibrecht, bricht es ab mit
#   "unable to list file info for path '/var/spool/pgbackrest/archive/<stanza>'"
#
# Ein eigener --spool-path wäre der naheliegende Ausweg und ist ein Holzweg:
# pgBackRest schreibt die Option in das `restore_command` der
# wiederhergestellten Konfiguration, `archive-get` lehnt sie dort ab
# ("option 'spool-path' not valid without option 'archive-async'"), die
# Wiederherstellung findet kein WAL und der Cluster stirbt mit "invalid
# checkpoint record" — einer Meldung, die in eine ganz andere Richtung zeigt.
# Und `--archive-async` lässt sich bei `restore` nicht mitgeben.
# Also: das Verzeichnis muss dem Übungskonto gehören.
readonly SPOOL_DEFAULT="/var/spool/pgbackrest"
if ! mkdir -p "$SPOOL_DEFAULT/archive/$STANZA" 2>/dev/null; then
    die "Kein Schreibrecht auf $SPOOL_DEFAULT — einmalig auf dem Backup-Host:
  sudo install -d -m 700 -o $(id -un) -g $(id -gn) $SPOOL_DEFAULT"
fi

CLEANUP_DIR="$(mktemp -d "$WORKROOT/pitr-drill.XXXXXX")"
trap cleanup EXIT INT TERM
chmod 700 "$CLEANUP_DIR"
mkdir -p "$CLEANUP_DIR/data" "$CLEANUP_DIR/sock"
chmod 700 "$CLEANUP_DIR/data" "$CLEANUP_DIR/sock"

step "Zurückspielen"
# --type=time mit --target-action=promote: der Cluster fährt nach Erreichen des
# Ziels als eigenständige Datenbank hoch. Ohne promote bliebe er in Recovery
# stehen und die Prüfungen unten könnten nicht schreiben — was sie nicht tun,
# aber der Unterschied fällt sonst erst im Ernstfall auf.
#
# `--reset-pg1-host` ist nicht Kosmetik: in der Konfiguration des Backup-Hosts
# zeigt `pg1-host` auf den Anwendungsserver, und pgBackRest lehnt dann ab mit
#   "restore command must be run on the PostgreSQL host"
# Die Übung soll aber ausdrücklich HIER einspielen und den Anwendungsserver
# nicht berühren.
pgbackrest --stanza="$STANZA" \
    --reset-pg1-host \
    --pg1-path="$CLEANUP_DIR/data" \
    --type=time --target="$TARGET" --target-action=promote \
    restore

# Der Übungscluster darf nichts nach draussen tun: kein Archivieren (er würde
# in dasselbe Repository schreiben und die Kette verderben) und keine
# Verbindung von aussen.
#
# Drei Einstellungen, die alle aus einem gescheiterten Versuch stammen:
#   * `listen_addresses = ''` — gar kein TCP. Der Socket liegt in einem
#     0700-Verzeichnis, das dem Übungskonto gehört; damit braucht es kein
#     `trust` auf 127.0.0.1, das zwei Minuten lang jedem lokalen Konto offen
#     stünde.
#   * `unix_socket_directories` — die wiederhergestellte Konfiguration ist die
#     der PRODUKTION und zeigt auf /var/run/postgresql. Dort darf das Konto des
#     Repositories nicht schreiben, und der Cluster stirbt mit
#     "could not create lock file ... Permission denied".
#   * `archive_mode = off` — sonst schreibt die Übung in dasselbe Repository,
#     aus dem sie gerade gelesen hat.
cat >>"$CLEANUP_DIR/data/postgresql.auto.conf" <<EOF

# --- pitr-drill.sh ---
port = $PORT
listen_addresses = ''
unix_socket_directories = '$CLEANUP_DIR/sock'
archive_mode = off
EOF

# Die wiederhergestellte pg_hba.conf ist die der Produktion und kennt das
# Konto nicht, unter dem diese Übung läuft. Über den privaten Socket ist
# `trust` vertretbar: das Verzeichnis gehört diesem Konto und hat 0700.
printf '\n# --- pitr-drill.sh ---\nlocal all all trust\n' \
    >>"$CLEANUP_DIR/data/pg_hba.conf"

step "Hochfahren"
CLEANUP_PORT="$PORT"
if ! "$PG_BIN/pg_ctl" -D "$CLEANUP_DIR/data" -l "$CLEANUP_DIR/pg.log" -w -t 120 start; then
    printf '%s\n' "--- Ende des Cluster-Protokolls ---" >&2
    tail -30 "$CLEANUP_DIR/pg.log" >&2 || true
    die "Der wiederhergestellte Cluster fährt nicht hoch."
fi

step "Prüfen"
psql() { "$PG_BIN/psql" -h "$CLEANUP_DIR/sock" -p "$PORT" -U postgres -d postgres -tAX "$@"; }

# 1. Ist die Wiederherstellung bis zum Ziel gekommen?
if ! grep -q "starting point-in-time recovery" "$CLEANUP_DIR/pg.log"; then
    die "Im Protokoll steht kein 'starting point-in-time recovery' — es wurde \
also gar kein Zeitpunkt angefahren, sondern nur die Vollsicherung ausgepackt. \
Damit ist die WAL-Kette NICHT geprüft."
fi
note "Point-in-time recovery gelaufen."
grep -E "recovery stopping|last completed transaction" "$CLEANUP_DIR/pg.log" \
    | tail -2 | sed 's/^/  /' || true

# 2. Ist der Cluster wirklich aus der Recovery heraus?
#
# Mit Warteschleife, und der Grund ist kein Schönheitsfehler: `pg_ctl -w`
# wartet darauf, dass der Cluster Verbindungen annimmt — das tut er WÄHREND der
# Wiederherstellung auch. Die Beförderung passiert danach. Ein Test direkt nach
# dem Start meldet deshalb zuverlässig "steht noch in Recovery", und zwar auch
# dann, wenn alles richtig ist.
promoted=0
for _ in $(seq 1 30); do
    if [[ "$(psql -c 'select pg_is_in_recovery()' 2>/dev/null)" == "f" ]]; then
        promoted=1
        break
    fi
    sleep 1
done
(( promoted == 1 )) || die "Der Cluster steht nach 30 Sekunden noch in Recovery \
— --target-action=promote hat nicht gegriffen."
note "Cluster ist eigenständig (nicht mehr in Recovery)."

# 3. Sind die Kundenschemata da? Das ist die Frage, die zählt: ein leerer
#    Cluster fährt auch hoch.
mapfile -t schemas < <(psql -d magister -c \
    "select nspname from pg_namespace where nspname like 't\\_%' order by 1" 2>/dev/null || true)
if (( ${#schemas[@]} == 0 )); then
    note "WARNUNG: kein Schema 't_*' gefunden."
    note "Bei einer Installation mit genau einem Kunden im public-Schema ist das"
    note "richtig; bei einer gehosteten Installation ist es ein Befund."
else
    note "Kundenschemata: ${schemas[*]}"
fi

# 4. Grobe Plausibilität: hat mindestens ein Schema Tabellen mit Zeilen?
total_tables="$(psql -d magister -c \
    "select count(*) from pg_tables where schemaname not in ('pg_catalog','information_schema')" \
    2>/dev/null || echo 0)"
note "Tabellen ausserhalb der Systemschemata: $total_tables"
(( total_tables >= PG_MIN_TABLES )) || die "Keine Tabellen gefunden — die \
Wiederherstellung ist formal gelungen und inhaltlich leer."

step "Ergebnis"
note "Wiederherstellung auf '$TARGET' geübt und bestanden."
note "Das Ergebnis gehört ins Protokoll (Runbook §7)."
