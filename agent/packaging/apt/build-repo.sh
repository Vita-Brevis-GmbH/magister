#!/usr/bin/env bash
# build-repo.sh
#
# Baut ein signiertes apt-Repository aus einem oder mehreren .deb
# (Entscheid E18, Schritt 1 — gibt E10 frei: automatische Agenten-Updates).
#
#     ./build-repo.sh --out /srv/apt --key 'Magister Packaging' *.deb
#     ./build-repo.sh --out /srv/apt --unsigned *.deb        # nur zum Prüfen
#
# Die Passphrase des Signierschlüssels fragt gpg selbst — eine Freigabe ist
# ein Ereignis und kein Cron-Job, und ein Mensch darf dabei einmal tippen.
# Für einen unbeaufsichtigten Lauf (CI mit Wegwerfschlüssel):
#     ./build-repo.sh --out /srv/apt --key ... --passphrase-file /pfad *.deb
#
# **Was apt tatsächlich prüft.** Nicht das .deb. apt prüft die Signatur der
# Datei `Release`; die enthält die Prüfsumme von `Packages`, und `Packages`
# enthält die SHA-256 jedes .deb. Die Kette hängt also an genau einer
# Signatur — der über `Release`. Ein "signiertes .deb" (dpkg-sig) prüft apt
# von sich aus überhaupt nicht.
#
# **Warum `apt-ftparchive` und nicht reprepro/aptly.** Für eine Handvoll
# Pakete aus einer Quelle braucht es keine Datenbank, keinen Zustand und kein
# zweites Werkzeug, das man alle zwei Jahre neu lernt. apt-ftparchive gehört zu
# apt selbst: es ist auf jedem Debian und Ubuntu da und veraltet nicht anders
# als apt. Kommen später mehrere Suites mit Aufstiegspfad dazu, ist reprepro
# der richtige Schritt — dann aber aus einem Bedarf und nicht vorsorglich.
#
# Referenz: agent/packaging/apt/README.md, ADR-0014.

set -euo pipefail

readonly SUITE="stable"
readonly COMPONENT="main"
readonly ORIGIN="Vita Brevis GmbH"
readonly LABEL="Magister"
readonly DESCRIPTION="Magister Connector Agent"

OUT=""
KEY=""
UNSIGNED=0
PASSFILE=""
DEBS=()

die() { printf 'FEHLER: %s\n' "$*" >&2; exit 1; }
note() { printf '  %s\n' "$*"; }
step() { printf '\n=== %s ===\n' "$*"; }

usage() {
    awk 'NR>=3 && /^#/ { sub(/^# ?/, ""); print; next } NR>=3 { exit }' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --out) OUT="$2"; shift 2 ;;
        --key) KEY="$2"; shift 2 ;;
        --unsigned) UNSIGNED=1; shift ;;
        --passphrase-file) PASSFILE="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        -*) die "Unbekannte Option: $1" ;;
        *) DEBS+=("$1"); shift ;;
    esac
done

[[ -n "$OUT" ]] || die "--out fehlt."
(( ${#DEBS[@]} > 0 )) || die "Kein .deb angegeben."
if (( UNSIGNED == 0 )); then
    [[ -n "$KEY" ]] || die "--key fehlt (oder --unsigned, aber das ist kein \
Repository für Kunden: apt lehnt es ab, und wer es mit 'trusted=yes' benutzt, \
hat die Signaturprüfung ausgeschaltet)."
fi
for tool in apt-ftparchive dpkg-deb; do
    command -v "$tool" >/dev/null || die "$tool fehlt (Paket apt-utils)."
done
(( UNSIGNED == 1 )) || command -v gpg >/dev/null || die "gpg fehlt."

for deb in "${DEBS[@]}"; do
    [[ -f "$deb" ]] || die "'$deb' nicht gefunden."
    dpkg-deb --info "$deb" >/dev/null 2>&1 || die "'$deb' ist kein gültiges Paket."
done

step "Struktur"
# Der Aufbau mit dists/ und pool/, nicht ein flaches Repository. Ein flaches
# funktioniert auch, kennt aber keine Suite — und die brauchen wir für E10:
# "stable" ist, was ein Agent automatisch zieht, und ein neuer Stand kann
# vorher irgendwo anders liegen.
BIN_DIR="$OUT/dists/$SUITE/$COMPONENT/binary-amd64"
POOL_DIR="$OUT/pool/$COMPONENT/m/magister-connector"
install -d "$BIN_DIR" "$POOL_DIR"
note "$OUT/dists/$SUITE/$COMPONENT/binary-amd64"
note "$OUT/pool/$COMPONENT/m/magister-connector"

for deb in "${DEBS[@]}"; do
    install -m 644 "$deb" "$POOL_DIR/$(basename "$deb")"
    note "$(basename "$deb")"
done

step "Packages"
# Aus $OUT heraus, damit die Pfade in Packages relativ zur Wurzel des
# Repositories stehen. Absolut wären sie so falsch, dass apt sie nicht
# einmal versucht.
( cd "$OUT" && apt-ftparchive packages "pool/$COMPONENT" >"$BIN_DIR/Packages" )
gzip -9cn "$BIN_DIR/Packages" >"$BIN_DIR/Packages.gz"
note "$(grep -c '^Package: ' "$BIN_DIR/Packages") Paket(e)"

# Ohne Release-Datei je Architektur meckern manche apt-Fassungen; sie kostet
# vier Zeilen.
cat >"$BIN_DIR/Release" <<EOF
Archive: $SUITE
Component: $COMPONENT
Origin: $ORIGIN
Label: $LABEL
Architecture: amd64
EOF

step "Release"
cat >"$OUT/apt-ftparchive.conf" <<EOF
APT::FTPArchive::Release::Origin "$ORIGIN";
APT::FTPArchive::Release::Label "$LABEL";
APT::FTPArchive::Release::Suite "$SUITE";
APT::FTPArchive::Release::Codename "$SUITE";
APT::FTPArchive::Release::Architectures "amd64";
APT::FTPArchive::Release::Components "$COMPONENT";
APT::FTPArchive::Release::Description "$DESCRIPTION";
EOF
( cd "$OUT" && apt-ftparchive -c apt-ftparchive.conf release "dists/$SUITE" \
    >"dists/$SUITE/Release.tmp" )
mv "$OUT/dists/$SUITE/Release.tmp" "$OUT/dists/$SUITE/Release"
rm -f "$OUT/apt-ftparchive.conf"

# `Valid-Until` ist der Grund, warum dieses Repository ein Datum braucht: ohne
# es akzeptiert apt eine beliebig alte, korrekt signierte Release-Datei. Wer
# einmal eine Version mit einer Lücke ausgeliefert hat, kann sie damit
# unbegrenzt weiter ausliefern (Replay). 30 Tage heisst: das Repository muss
# mindestens monatlich neu signiert werden, auch wenn sich nichts geändert hat.
if ! grep -q '^Valid-Until:' "$OUT/dists/$SUITE/Release"; then
    valid_until="$(date -u -d '+30 days' '+%a, %d %b %Y %H:%M:%S UTC')"
    # Hinter die Date-Zeile, damit der Kopf zusammenbleibt.
    awk -v vu="$valid_until" '
        { print }
        /^Date:/ && !done { print "Valid-Until: " vu; done = 1 }
    ' "$OUT/dists/$SUITE/Release" >"$OUT/dists/$SUITE/Release.tmp"
    mv "$OUT/dists/$SUITE/Release.tmp" "$OUT/dists/$SUITE/Release"
fi
note "$(grep -E '^(Date|Valid-Until):' "$OUT/dists/$SUITE/Release" | tr '\n' ' ')"

if (( UNSIGNED == 1 )); then
    step "Nicht signiert"
    note "Release.gpg und InRelease fehlen. apt lehnt dieses Repository ab —"
    note "richtig so. Zum Ausliefern mit --key erneut bauen."
    exit 0
fi

step "Signieren"
rm -f "$OUT/dists/$SUITE/Release.gpg" "$OUT/dists/$SUITE/InRelease"

# **Kein `--batch` beim Signieren.** Mit `--batch` darf gpg nicht nachfragen,
# und ein passphrasegeschützter Schlüssel — also der, den wir empfehlen —
# scheitert dann mit „signing failed: Inappropriate ioctl for device". Das ist
# nicht theoretisch: mit `--batch` liess sich mit dem vorgesehenen
# Unterschlüssel überhaupt nichts freigeben.
GPG_OPTS=(--yes --local-user "$KEY")
if [[ -n "$PASSFILE" ]]; then
    [[ -f "$PASSFILE" ]] || die "Passphrase-Datei '$PASSFILE' nicht gefunden."
    # `--pinentry-mode loopback` ist dabei Pflicht: ohne sie ignoriert gpg 2.x
    # die Datei und will trotzdem den Agenten fragen.
    GPG_OPTS+=(--batch --pinentry-mode loopback --passphrase-file "$PASSFILE")
fi

# Beides: InRelease (Signatur und Inhalt in einer Datei, was apt bevorzugt) und
# Release.gpg daneben, für ältere apt-Fassungen auf noch unterstützten
# Debian-Ständen.
gpg "${GPG_OPTS[@]}" --armor --detach-sign \
    --output "$OUT/dists/$SUITE/Release.gpg" "$OUT/dists/$SUITE/Release" \
    || die "Signieren scheiterte. Bei 'Inappropriate ioctl for device' fehlt \
der Weg zur Passphrase: entweder in einer Sitzung mit Terminal aufrufen, oder \
--passphrase-file mitgeben."
gpg "${GPG_OPTS[@]}" --clearsign \
    --output "$OUT/dists/$SUITE/InRelease" "$OUT/dists/$SUITE/Release" \
    || die "Clearsign scheiterte (siehe oben)."
note "Release.gpg und InRelease geschrieben."

step "Selbst nachprüfen"
# Nicht Höflichkeit: eine Signatur, die niemand prüft, ist eine Datei. Und ein
# falscher --key (etwa ein abgelaufener Unterschlüssel) fällt sonst erst beim
# Kunden auf.
gpg --verify "$OUT/dists/$SUITE/Release.gpg" "$OUT/dists/$SUITE/Release" 2>&1 \
    | sed 's/^/  /'
gpg --verify "$OUT/dists/$SUITE/InRelease" >/dev/null 2>&1 \
    || die "InRelease verifiziert nicht."
note "Beide Signaturen prüfen durch."

step "Öffentlichen Schlüssel mitliefern"
# Als Datei im Repository, damit die Installationsanleitung eine Adresse
# nennen kann statt eines Schlüsselservers.
gpg --batch --yes --export --armor "$KEY" >"$OUT/magister-archive-keyring.asc"
note "$OUT/magister-archive-keyring.asc"
note "Fingerprint:"
gpg --batch --with-colons --fingerprint "$KEY" \
    | awk -F: '$1 == "fpr" { print "    " $10; exit }'

step "Fertig"
note "Verzeichnis $OUT ausliefern (statisch, HTTPS). Kundenzeile:"
note "  deb [signed-by=/etc/apt/keyrings/magister-archive-keyring.gpg] \\"
note "      https://apt.magister.ch/ $SUITE $COMPONENT"
note ""
note "Erinnerung: Valid-Until läuft in 30 Tagen ab. Ein Repository, das nicht"
note "neu signiert wird, hört auf zu funktionieren — das ist der Preis dafür,"
note "dass ein alter Stand nicht unbegrenzt wiedereingespielt werden kann."
