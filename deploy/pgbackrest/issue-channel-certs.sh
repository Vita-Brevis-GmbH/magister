#!/usr/bin/env bash
# issue-channel-certs.sh
#
# Erzeugt die kleine CA des Sicherungskanals und die zwei Zertifikate, mit
# denen sich Anwendungsserver und Backup-Host gegenseitig ausweisen
# (ADR-0016 Ebene 1, Entscheid E17).
#
# Läuft auf dem BACKUP-HOST. Der private Schlüssel der Kanal-CA bleibt dort.
#
# Warum eine eigene CA und nicht die Plattform-CA: die Plattform-CA beglaubigt
# Agenten und Operatoren, liegt offline im Tresor und wird für eine Zeremonie
# herausgeholt. Ein Zertifikat, das beim Aufsetzen eines Backup-Hosts gebraucht
# wird, darf nicht von einem Schlüssel abhängen, für den zwei Personen und ein
# Tresorgang nötig sind — und ein Widerruf hier soll die Agent-Flotte nicht
# berühren. Dieselbe Begründung wie für die zwei getrennten Intermediates in
# docs/runbooks/platform-ca.md §2.
#
# Usage:
#   ./issue-channel-certs.sh --out /etc/pgbackrest/cert \
#       --app app.magister.intern --backup backup.magister.intern

set -euo pipefail

readonly CURVE="prime256v1"
readonly DIGEST="sha256"
readonly CA_DAYS=3650
readonly LEAF_DAYS=825   # die übliche Obergrenze; erneuern ist ein Aufruf

OUT=""
APP_NAME=""
BACKUP_NAME=""

die() { printf 'FEHLER: %s\n' "$*" >&2; exit 1; }
note() { printf '  %s\n' "$*"; }
step() { printf '\n=== %s ===\n' "$*"; }

usage() {
    awk 'NR>=3 && /^#/ { sub(/^# ?/, ""); print; next } NR>=3 { exit }' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --out) OUT="$2"; shift 2 ;;
        --app) APP_NAME="$2"; shift 2 ;;
        --backup) BACKUP_NAME="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unbekannte Option: $1" ;;
    esac
done

[[ -n "$OUT" ]] || die "--out fehlt."
[[ -n "$APP_NAME" ]] || die "--app fehlt (der Name, unter dem der Backup-Host \
den Anwendungsserver erreicht — genau dieser Name, nicht die IP)."
[[ -n "$BACKUP_NAME" ]] || die "--backup fehlt."

# Der Name muss der sein, der in pgbackrest.conf steht: pgBackRest prüft
# Hostname gegen CN/SAN und bricht sonst ab. Ein Tippfehler hier kostet eine
# halbe Stunde Suchen an der falschen Stelle.
for name in "$APP_NAME" "$BACKUP_NAME"; do
    [[ "$name" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] \
        || die "'$name' sieht nicht wie ein Hostname aus."
    [[ "$name" =~ ^[0-9.]+$ ]] \
        && die "'$name' ist eine IP-Adresse. Das verlangt ein Zertifikat mit \
IP-SAN; nimm einen Namen, der einen Adresswechsel überlebt."
done

install -d -m 700 "$OUT"
cd "$OUT"

issue() {  # $1 = CN, $2 = Dateiname
    local cn="$1" base="$2"
    [[ -e "$base.key" ]] && die "$OUT/$base.key existiert schon — nicht überschreiben."
    ( umask 077 && openssl ecparam -name "$CURVE" -genkey -noout -out "$base.key" )
    openssl req -new -"$DIGEST" -key "$base.key" -out "$base.csr" \
        -subj "/C=CH/O=Vita Brevis GmbH/CN=$cn"
    # serverAuth UND clientAuth: beide Seiten sind beides. Der Anwendungsserver
    # ist Client, wenn er WAL schiebt, und Server, wenn der Backup-Host die
    # Sicherung anstösst.
    openssl x509 -req -in "$base.csr" \
        -CA backup-channel-ca.crt -CAkey backup-channel-ca.key -CAcreateserial \
        -"$DIGEST" -days "$LEAF_DAYS" -out "$base.crt" \
        -extfile <(printf 'keyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth,clientAuth\nsubjectAltName=DNS:%s\n' "$cn")
    rm -f "$base.csr"
    chmod 600 "$base.key"
    chmod 644 "$base.crt"
    note "$base.crt für CN=$cn"
}

step "Kanal-CA ($CA_DAYS Tage)"
if [[ -e backup-channel-ca.key ]]; then
    note "Existiert schon — wird weiterverwendet."
else
    ( umask 077 && openssl ecparam -name "$CURVE" -genkey -noout -out backup-channel-ca.key )
    openssl req -new -x509 -"$DIGEST" -days "$CA_DAYS" \
        -key backup-channel-ca.key -out backup-channel-ca.crt \
        -subj "/C=CH/O=Vita Brevis GmbH/CN=Magister Backup Channel CA" \
        -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
        -addext "keyUsage=critical,keyCertSign"
    chmod 600 backup-channel-ca.key
    chmod 644 backup-channel-ca.crt
    note "backup-channel-ca.crt erzeugt."
fi

step "Zertifikate"
issue "$BACKUP_NAME" backup
issue "$APP_NAME" app

step "Kette prüfen"
openssl verify -CAfile backup-channel-ca.crt backup.crt app.crt

step "Nächster Schritt"
note "Auf den ANWENDUNGSSERVER gehören genau drei Dateien:"
note "  app.crt, app.key, backup-channel-ca.crt   (nach /etc/pgbackrest/cert)"
note "Der Schlüssel der CA und backup.key bleiben HIER."
note ""
note "Restlaufzeit der Zertifikate: $LEAF_DAYS Tage. Das Erneuern ist derselbe"
note "Aufruf; in den Kalender damit, sonst steht die Archivierung an einem"
note "Dienstag ohne Vorwarnung."
