#!/usr/bin/env bash
# platform-ca-ceremony.sh
#
# Führt die Zeremonien der Plattform-CA schrittweise durch (ADR-0014, ADR-0015 D1).
# Läuft auf dem Offline-Rechner, nie auf einem Server mit Netzverbindung.
#
# Warum es diesen Script gibt: die Kommandos im Runbook sind lang, und ein
# Tippfehler in einer Extension fällt erst Jahre später auf — dann als
# Zertifikat, das nicht mehr auszutauschen ist, ohne die ganze Flotte
# anzufassen. Der Script schreibt zusätzlich das Protokoll mit, damit die
# Fingerprints nicht von Hand abgeschrieben werden.
#
# Die Passphrase des Datenträgers berührt dieser Script nie: `cryptsetup`
# fragt sie selbst, sie erscheint in keiner Variable, keinem Log, keinem
# Protokoll.
#
# Usage (offline, auf dem Live-System):
#   ./scripts/platform-ca-ceremony.sh preflight
#   ./scripts/platform-ca-ceremony.sh root        --workdir /mnt/ceremony \
#         --live-image debian-live-12.5-amd64-standard.iso --live-sha256 <64 hex>
#   ./scripts/platform-ca-ceremony.sh stick       --workdir /mnt/ceremony --device /dev/sdX
#   ./scripts/platform-ca-ceremony.sh intermediate --workdir /mnt/ceremony \
#         --csr connector-int.csr --purpose connector \
#         --live-image ... --live-sha256 ...
#   ./scripts/platform-ca-ceremony.sh verify      --workdir /mnt/ceremony
#
# Usage (danach, auf einem Rechner MIT Netz und Repository-Klon):
#   ./scripts/platform-ca-ceremony.sh protokoll   --file /mnt/transport/PROTOKOLL.md
#
# Entscheid E20: die Zeremonie läuft auf einem Live-System, dessen Hash im
# Protokoll steht — deshalb sind --live-image und --live-sha256 bei 'root' und
# 'intermediate' Pflicht und keine Höflichkeit.
#
# Entscheid E19: das Protokoll lebt auf dem Stick UND im Repository unter
# docs/ca/. 'protokoll' legt es dort ab und prüft es vorher auf Geheimnisse.
#
# Runbook: docs/runbooks/platform-ca.md

set -euo pipefail

# --- Parameter aus dem Runbook. Ändern heisst: Runbook mitändern. -----------
readonly CURVE="secp384r1"
readonly DIGEST="sha384"
readonly ROOT_DAYS=7300  # 20 Jahre
readonly INT_DAYS=1826   # 5 Jahre
readonly SUBJ_O="Vita Brevis GmbH"
readonly SUBJ_C="CH"
readonly ROOT_CN="Vita Brevis Magister Root CA"

# Die beiden Schlüsselverwahrer (Entscheid E9). Sie zeichnen jedes Protokoll.
readonly KEY_HOLDERS="Matthias Hadorn, Rolf Straubhaar"

WORKDIR=""
DEVICE=""
CSR=""
PURPOSE=""
LIVE_IMAGE=""
LIVE_SHA256=""
PROTO_FILE=""
REPO_DIR=""

# Aufräum-Zustand. Bewusst global und nicht `local` in cmd_stick: der
# EXIT-Trap läuft, wenn der Funktionsrahmen längst weg ist — mit Locals
# stirbt der Handler unter `set -u` an einer unbound variable und lässt
# genau den Zustand zurück, den er verhindern soll: einen entsperrten,
# gemounteten Datenträger mit dem Root-Schlüssel darauf.
CLEANUP_MNT=""
CLEANUP_MAPPER=""

cleanup() {
    # Jeder Schritt einzeln und mit `|| true`: schlägt das umount fehl, muss
    # das `cryptsetup close` trotzdem laufen. Ein `&&`-Einzeiler würde hier
    # unter `set -e` abbrechen und den Datenträger entsperrt zurücklassen.
    if [[ -n "$CLEANUP_MNT" ]]; then
        umount "$CLEANUP_MNT" 2>/dev/null || true
    fi
    if [[ -n "$CLEANUP_MAPPER" ]]; then
        cryptsetup close "$CLEANUP_MAPPER" 2>/dev/null || true
    fi
    if [[ -n "$CLEANUP_MNT" ]]; then
        rmdir "$CLEANUP_MNT" 2>/dev/null || true
    fi
    CLEANUP_MNT=""
    CLEANUP_MAPPER=""
    return 0
}

die() { printf 'FEHLER: %s\n' "$*" >&2; exit 1; }
note() { printf '  %s\n' "$*"; }
step() { printf '\n=== %s ===\n' "$*"; }

usage() {
    # Ab Zeile 3 bis zur ersten Nicht-Kommentarzeile. Eine feste Zeilenspanne
    # ("sed -n 3,26p") war hier schon einmal falsch, nachdem der Kopf gewachsen
    # war — dann fehlt der Hilfe genau der neue Befehl.
    awk 'NR>=3 && /^#/ { sub(/^# ?/, ""); print; next } NR>=3 { exit }' "$0"
}

# --- Protokoll --------------------------------------------------------------
# Papier bleibt das gültige Protokoll (beide Unterschriften). Diese Datei ist
# die Vorlage dafür, damit Seriennummern und Fingerprints nicht abgetippt
# werden. Sie enthält nie eine Passphrase und nie einen privaten Schlüssel.
log_protocol() {
    local file="$WORKDIR/PROTOKOLL.md"
    printf '%s\n' "$*" >>"$file"
}

require_workdir() {
    [[ -n "$WORKDIR" ]] || die "--workdir fehlt."
    [[ -d "$WORKDIR" ]] || die "--workdir '$WORKDIR' existiert nicht."
    # 0700: auf einem Live-System läuft man als root, aber ein zweiter
    # Terminal-Benutzer soll den Schlüssel nicht lesen können.
    chmod 700 "$WORKDIR"
}

fingerprint() {
    openssl x509 -in "$1" -noout -fingerprint -"$DIGEST" | cut -d= -f2
}

serial() {
    openssl x509 -in "$1" -noout -serial | cut -d= -f2
}

# --- Live-System (Entscheid E20) --------------------------------------------
# Entschieden ist: kein dediziertes Gerät, sondern ein Live-System, dessen Hash
# im Protokoll steht. Damit das eine Eigenschaft und nicht eine Absicht ist,
# prüft und protokolliert der Script beides — den Hash, den nur ein Mensch
# kennen kann, und die Identität, die sich auslesen lässt.

# Dateisysteme, auf denen ein Neustart wirklich alles mitnimmt.
readonly VOLATILE_FSTYPES="overlay tmpfs ramfs squashfs aufs"

root_fstype() {
    if command -v findmnt >/dev/null 2>&1; then
        findmnt -no FSTYPE / 2>/dev/null && return 0
    fi
    # Ohne findmnt: die letzte / -Zeile in /proc/mounts gewinnt (spätere
    # Mounts überdecken frühere).
    awk '$2 == "/" { fs = $3 } END { print fs }' /proc/mounts
}

root_is_volatile() {
    local fs
    fs="$(root_fstype)"
    local candidate
    for candidate in $VOLATILE_FSTYPES; do
        [[ "$fs" == "$candidate" ]] && return 0
    done
    return 1
}

system_identity() {
    local pretty="unbekannt"
    if [[ -r /etc/os-release ]]; then
        # Kein `source`: /etc/os-release ist zwar Shell-Syntax, aber eine
        # Datei ausführen, um einen Namen zu lesen, ist der falsche Handgriff.
        pretty="$(sed -n 's/^PRETTY_NAME="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' /etc/os-release | head -1)"
        [[ -n "$pretty" ]] || pretty="unbekannt"
    fi
    printf '%s, Kernel %s, / auf %s' "$pretty" "$(uname -r)" "$(root_fstype)"
}

require_live_evidence() {
    [[ -n "$LIVE_IMAGE" ]] || die "--live-image fehlt. Entscheid E20 verlangt, dass \
im Protokoll steht, WOMIT die Zeremonie gefahren wurde (Dateiname des ISO)."
    [[ -n "$LIVE_SHA256" ]] || die "--live-sha256 fehlt. Den Hash des ISO nehmen, \
mit dem der Boot-Stick geschrieben wurde:
  sha256sum <image>.iso
Er muss mit dem signierten SHA256SUMS des Herstellers übereinstimmen — sonst
protokolliert man den Hash von etwas, das schon manipuliert war."
    [[ "$LIVE_SHA256" =~ ^[0-9a-fA-F]{64}$ ]] \
        || die "--live-sha256 ist kein SHA-256 (64 Hex-Zeichen): '$LIVE_SHA256'"
    # Kleinschreibung, damit zwei Protokolle vergleichbar sind.
    LIVE_SHA256="$(printf '%s' "$LIVE_SHA256" | tr 'A-F' 'a-f')"

    if ! root_is_volatile; then
        note "WARNUNG: / liegt auf '$(root_fstype)' — das sieht nach einem"
        note "installierten System aus, nicht nach einem Live-System."
        read -r -p "Trotzdem fortfahren? Der Grund gehört ins Protokoll. [ja/nein] " confirm
        [[ "$confirm" == "ja" ]] || die "Abgebrochen."
    fi
}

log_live_evidence() {
    log_protocol "- Live-System: $LIVE_IMAGE"
    log_protocol "- Live-System SHA-256: $LIVE_SHA256"
    log_protocol "- Erkannt: $(system_identity)"
}

# --- preflight --------------------------------------------------------------
# Prüft, was sich prüfen lässt. Die Netzprüfung ist ein Hinweis, kein Beweis:
# eine fehlende Default-Route heisst nicht, dass kein Interface aktiv ist.
cmd_preflight() {
    local problems=0
    local warnings=0

    step "Werkzeuge"
    for tool in openssl cryptsetup sha256sum; do
        if command -v "$tool" >/dev/null 2>&1; then
            note "$tool: $(command -v "$tool")"
        elif [[ "$tool" == "cryptsetup" ]]; then
            # Nur 'stick' braucht cryptsetup. Fehlt es, kann man 'root' und
            # 'intermediate' fahren — aber ohne Datenträger endet die Zeremonie
            # mit einem Root-Schlüssel im tmpfs, also nirgends.
            note "cryptsetup: FEHLT — 'stick' ist damit nicht möglich."
            warnings=$((warnings + 1))
        else
            note "$tool: FEHLT"
            problems=$((problems + 1))
        fi
    done

    step "Netz"
    if ip route show default 2>/dev/null | grep -q .; then
        note "Es gibt eine Default-Route — der Rechner hängt am Netz."
        note "Kabel ziehen, WLAN aus, dann erneut prüfen."
        problems=$((problems + 1))
    else
        note "Keine Default-Route. (Kein Beweis, aber das erwartete Bild.)"
    fi

    step "Live-System (Entscheid E20)"
    note "$(system_identity)"
    if root_is_volatile; then
        note "/ ist flüchtig — das erwartete Bild für ein Live-System."
    else
        note "/ liegt auf '$(root_fstype)': ein installiertes System."
        note "Entschieden ist ein Live-System vom Stick (Entscheid E20, Variante A)."
        note "Kein Beweis in die andere Richtung — aber hier ist es ein Befund."
        problems=$((problems + 1))
    fi
    note "Der Hash des ISO gehört ins Protokoll und ist bei 'root' und"
    note "'intermediate' Pflicht: --live-image <datei> --live-sha256 <64 hex>"

    step "Persistenz"
    note "Dieser Script legt Schlüssel im --workdir ab. Auf einem Live-System"
    note "soll das ein tmpfs sein, damit nichts eine Neustartgrenze überlebt:"
    note "  mount -t tmpfs -o size=64m,mode=700 tmpfs /mnt/ceremony"

    step "Anwesenheit"
    note "Zeremonie nur zu zweit: $KEY_HOLDERS"

    if (( problems > 0 )); then
        die "$problems Punkt(e) offen — nicht fortfahren."
    fi
    if (( warnings > 0 )); then
        printf '\nPreflight bestanden, aber %d Hinweis(e) oben lesen.\n' "$warnings"
    else
        printf '\nPreflight in Ordnung.\n'
    fi
}

# --- root -------------------------------------------------------------------
cmd_root() {
    require_workdir
    require_live_evidence
    [[ -e "$WORKDIR/root.key" ]] && die "root.key existiert schon in $WORKDIR — \
niemals über einen bestehenden Root schreiben."

    step "Root-Schlüssel (ECDSA $CURVE)"
    ( umask 077 && openssl ecparam -name "$CURVE" -genkey -noout -out "$WORKDIR/root.key" )
    chmod 400 "$WORKDIR/root.key"
    note "root.key erzeugt (0400)."

    step "Root-Zertifikat ($ROOT_DAYS Tage)"
    # pathlen:1 — der Root darf Intermediates signieren, diese aber keine
    # weiteren CAs. Ohne diese Grenze könnte ein kompromittiertes Intermediate
    # eine eigene Sub-CA aufziehen.
    openssl req -new -x509 -"$DIGEST" -days "$ROOT_DAYS" \
        -key "$WORKDIR/root.key" -out "$WORKDIR/root.crt" \
        -subj "/C=$SUBJ_C/O=$SUBJ_O/CN=$ROOT_CN" \
        -addext "basicConstraints=critical,CA:TRUE,pathlen:1" \
        -addext "keyUsage=critical,keyCertSign,cRLSign"

    local fp ser
    fp="$(fingerprint "$WORKDIR/root.crt")"
    ser="$(serial "$WORKDIR/root.crt")"
    note "Fingerprint ($DIGEST): $fp"
    note "Seriennummer:          $ser"

    log_protocol ""
    log_protocol "## Root-CA erzeugt"
    log_protocol ""
    log_protocol "- Datum: $(date -u '+%Y-%m-%d %H:%M UTC')"
    log_protocol "- Anwesend: $KEY_HOLDERS"
    log_protocol "- Subject: /C=$SUBJ_C/O=$SUBJ_O/CN=$ROOT_CN"
    log_protocol "- Gültig: $ROOT_DAYS Tage"
    log_protocol "- Seriennummer: $ser"
    log_protocol "- Fingerprint ($DIGEST): $fp"
    log_live_evidence
    log_protocol "- Unterschriften: ________________  ________________"

    step "Nächster Schritt"
    note "Zwei Sticks schreiben:"
    note "  $0 stick --workdir $WORKDIR --device /dev/sdX"
}

# --- stick ------------------------------------------------------------------
cmd_stick() {
    require_workdir
    [[ -n "$DEVICE" ]] || die "--device fehlt (z. B. /dev/sdb)."
    [[ -b "$DEVICE" ]] || die "'$DEVICE' ist kein Blockgerät."
    [[ -f "$WORKDIR/root.key" && -f "$WORKDIR/root.crt" ]] \
        || die "root.key/root.crt fehlen in $WORKDIR — zuerst 'root' ausführen."
    [[ "$(id -u)" -eq 0 ]] || die "Muss als root laufen (cryptsetup, mount)."

    step "Warnung"
    note "$DEVICE wird vollständig überschrieben:"
    lsblk -o NAME,SIZE,MODEL,MOUNTPOINT "$DEVICE" || true
    read -r -p "Gerätepfad zur Bestätigung erneut eingeben: " confirm
    [[ "$confirm" == "$DEVICE" ]] || die "Eingabe stimmt nicht — abgebrochen."

    local mapper="magister-ca-ceremony"
    local mnt
    mnt="$(mktemp -d)"
    # Ab hier räumt der Trap auf, auch bei Abbruch mitten in der Zeremonie.
    CLEANUP_MNT="$mnt"
    CLEANUP_MAPPER="$mapper"
    trap cleanup EXIT INT TERM

    step "LUKS anlegen (Passphrase wird von cryptsetup erfragt)"
    note "Die Passphrase gehört in zwei versiegelte Umschläge, je einer bei"
    note "einem Verwahrer — NICHT in den Tresor zum Stick (Runbook §3)."
    cryptsetup luksFormat --type luks2 --pbkdf argon2id "$DEVICE"

    step "Dateisystem und Inhalt"
    cryptsetup open "$DEVICE" "$mapper"
    mkfs.ext4 -q -L magister-ca "/dev/mapper/$mapper"
    mount "/dev/mapper/$mapper" "$mnt"
    install -m 400 "$WORKDIR/root.key" "$mnt/root.key"
    install -m 444 "$WORKDIR/root.crt" "$mnt/root.crt"
    # SHA256SUMS deckt nur die beiden unveränderlichen Dateien ab. Das
    # Protokoll wächst mit jeder Zeremonie und gehört deshalb nicht hinein —
    # sonst schlägt die Jahreskontrolle jedes Mal fehl.
    ( cd "$mnt" && sha256sum root.key root.crt >SHA256SUMS )
    ( cd "$mnt" && sha256sum -c SHA256SUMS >/dev/null ) || die "Prüfsummen stimmen nicht."
    # Das Protokoll enthält keine Geheimnisse, nur Fingerprints und
    # Seriennummern — und es muss den Neustart überleben, der das tmpfs
    # löscht. Auf dem Stick liegt es dort, wo man es beim nächsten Mal sucht.
    if [[ -f "$WORKDIR/PROTOKOLL.md" ]]; then
        install -m 444 "$WORKDIR/PROTOKOLL.md" "$mnt/PROTOKOLL.md"
        note "PROTOKOLL.md mitgeschrieben (nicht in SHA256SUMS, es wächst noch)."
    fi
    sync
    note "root.key, root.crt, SHA256SUMS geschrieben und geprüft."

    cleanup
    trap - EXIT INT TERM

    log_protocol ""
    log_protocol "- Stick geschrieben: $(date -u '+%Y-%m-%d %H:%M UTC'), LUKS2/argon2id, Ablage Tresor"

    step "Nächster Schritt"
    note "Zweiten Stick mit demselben Kommando und derselben Passphrase schreiben."
    note "Danach das Papierprotokoll ausfüllen und unterschreiben — die Datei"
    note "PROTOKOLL.md ist nur die Vorlage, gültig ist die Unterschrift."
    note "Erst dann: Live-System neu starten. Damit ist root.key aus dem tmpfs"
    note "weg und existiert nur noch auf den beiden Sticks."
    note ""
    note "Vor dem Neustart: PROTOKOLL.md auch auf einen dritten, gewöhnlichen"
    note "TRANSPORT-Stick kopieren (Entscheid E19 — das Protokoll gehört ins"
    note "Repository). Nur diese eine Datei. Der CA-Stick darf nie an einem"
    note "Rechner mit Netz hängen, und genau dort läuft der nächste Schritt:"
    note "  $0 protokoll --file /mnt/transport/PROTOKOLL.md"
}

# --- intermediate -----------------------------------------------------------
cmd_intermediate() {
    require_workdir
    require_live_evidence
    [[ -n "$CSR" ]] || die "--csr fehlt."
    [[ -f "$CSR" ]] || die "CSR '$CSR' nicht gefunden."
    case "$PURPOSE" in
        connector|operator) ;;
        *) die "--purpose muss 'connector' oder 'operator' sein." ;;
    esac
    [[ -f "$WORKDIR/root.key" && -f "$WORKDIR/root.crt" ]] \
        || die "root.key/root.crt fehlen in $WORKDIR — Stick entsperrt und gemountet?"

    step "CSR prüfen"
    openssl req -in "$CSR" -noout -verify >/dev/null 2>&1 \
        || die "CSR-Selbstsignatur ungültig — nicht signieren."
    local csr_subj
    csr_subj="$(openssl req -in "$CSR" -noout -subject)"
    note "$csr_subj"
    read -r -p "Ist das der erwartete Subject? [ja/nein] " confirm
    [[ "$confirm" == "ja" ]] || die "Abgebrochen."

    local out="$WORKDIR/${PURPOSE}-int.crt"
    [[ -e "$out" ]] && die "$out existiert schon."

    step "Signieren ($INT_DAYS Tage)"
    # pathlen:0 — das Intermediate stellt Endzertifikate aus, keine weiteren CAs.
    local ext
    ext="$(mktemp)"
    printf 'basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\n' >"$ext"
    openssl x509 -req -in "$CSR" \
        -CA "$WORKDIR/root.crt" -CAkey "$WORKDIR/root.key" -CAcreateserial \
        -"$DIGEST" -days "$INT_DAYS" -out "$out" -extfile "$ext"
    rm -f "$ext"

    step "Kette prüfen"
    openssl verify -CAfile "$WORKDIR/root.crt" "$out" \
        || die "Kette verifiziert nicht — Zertifikat nicht ausliefern."

    local fp ser
    fp="$(fingerprint "$out")"
    ser="$(serial "$out")"
    note "Fingerprint ($DIGEST): $fp"
    note "Seriennummer:          $ser"

    log_protocol ""
    log_protocol "## Intermediate \"$PURPOSE\" ausgestellt"
    log_protocol ""
    log_protocol "- Datum: $(date -u '+%Y-%m-%d %H:%M UTC')"
    log_protocol "- Anwesend: $KEY_HOLDERS"
    log_protocol "- $csr_subj"
    log_protocol "- Gültig: $INT_DAYS Tage"
    log_protocol "- Seriennummer: $ser"
    log_protocol "- Fingerprint ($DIGEST): $fp"
    log_live_evidence
    log_protocol "- Unterschriften: ________________  ________________"

    step "Nächster Schritt"
    note "Nur $out zurück auf den Server. Der Root-Schlüssel bleibt hier."
    note "Und: PROTOKOLL.md auf einen TRANSPORT-Stick (unverschlüsselt, nur"
    note "diese Datei), danach an einem Rechner mit Netz:"
    note "  $0 protokoll --file /mnt/transport/PROTOKOLL.md"
}

# --- protokoll (Entscheid E19) ----------------------------------------------
# Läuft NICHT auf dem Offline-Rechner, sondern danach auf einem Rechner mit
# Netz und Repository-Klon. Die Datei kommt über einen gewöhnlichen
# Transport-Stick; der CA-Stick bleibt, wo er ist.
#
# Der Grund für die Prüfung unten: der Weg ins Repository ist der einzige Weg,
# auf dem etwas aus einer Zeremonie öffentlich werden kann. Wer im Eifer das
# ganze Arbeitsverzeichnis kopiert, kopiert den Root-Schlüssel mit. Diese
# Prüfung fängt nicht jede denkbare Form, aber die Formen, in denen ein
# Geheimnis tatsächlich in einer Datei landet.

# Zeilen, die ein Geheimnis SIND (nicht: davon reden).
readonly SECRET_PATTERNS=(
    '-----BEGIN [A-Z ]*PRIVATE KEY-----'
    'AGE-SECRET-KEY-1'
    'MK digest:'
)

# Gibt die Fundstellen mit Zeilennummer aus; leere Ausgabe heisst sauber.
scan_for_secrets() {
    local file="$1"
    local pattern rc
    for pattern in "${SECRET_PATTERNS[@]}"; do
        # `-e` ist hier nicht Geschmack: das erste Muster beginnt mit fünf
        # Bindestrichen, und ohne `-e` liest grep es als Optionen. Es lief
        # damit nie — und "kein Treffer" sah aus wie "sauber", genau bei dem
        # Muster, das einen privaten Schlüssel fängt.
        rc=0
        grep -nE -e "$pattern" "$file" || rc=$?
        # 0 = Treffer, 1 = kein Treffer, alles darüber = grep selbst kaputt.
        # Ohne diese Unterscheidung schaltet ein fehlerhaftes Muster die
        # Prüfung stillschweigend ab, und genau das ist gerade passiert.
        if (( rc > 1 )); then
            die "grep scheiterte an Muster '$pattern' (rc=$rc). Die Prüfung ist \
damit unvollständig — nichts kopiert."
        fi
    done
    # Ein Wort wie "Passphrase" darf im Protokoll stehen — "Passphrase in zwei
    # versiegelten Umschlägen" ist genau die Aussage, die hineingehört. Was
    # nicht hineingehört, ist ein WERT dahinter. Deshalb erst ab einem
    # Doppelpunkt oder Gleichheitszeichen, und nur wenn danach etwas steht,
    # das wie ein Wert aussieht und nicht wie eine Auslassung.
    #
    # Zwei Dinge sind hier absichtlich umständlich, beide gemessen:
    #   * `tolower()` statt `IGNORECASE` — auf Debian und Ubuntu ist awk
    #     **mawk**, und mawk kennt IGNORECASE nicht. Mit IGNORECASE traf die
    #     Regel "Passphrase" mit grossem P nie, also praktisch nie.
    #   * die Länge über `split()` statt über `{8,}` — Intervall-Ausdrücke
    #     sind auf mawk historisch unzuverlässig.
    awk '
        {
            low = tolower($0)
            if (low !~ /(passphrase|passwort|password)[ \t]*[:=]/) next
            rest = low
            sub(/^.*(passphrase|passwort|password)[ \t]*[:=][ \t]*/, "", rest)
            # Platzhalter und Verweise sind in Ordnung.
            if (rest ~ /^[_*.x -]*$/) next
            if (rest ~ /^(siehe|im |bei |zwei|getrennt|nicht|auf papier)/) next
            # Ein Wert hat keine Leerzeichen und ist lang genug, um einer zu sein.
            split(rest, token, /[ \t]/)
            if (length(token[1]) >= 8) printf "%d:%s\n", NR, $0
        }
    ' "$file" || true
}

cmd_protokoll() {
    local src="$PROTO_FILE"
    if [[ -z "$src" && -n "$WORKDIR" ]]; then
        src="$WORKDIR/PROTOKOLL.md"
    fi
    [[ -n "$src" ]] || die "--file fehlt (oder --workdir, dann PROTOKOLL.md darin)."
    [[ -f "$src" ]] || die "'$src' nicht gefunden."
    [[ -s "$src" ]] || die "'$src' ist leer — da war keine Zeremonie."

    local target_dir="$REPO_DIR"
    if [[ -z "$target_dir" ]]; then
        target_dir="$(cd "$(dirname "$0")/.." && pwd)/docs/ca"
    fi
    [[ -d "$target_dir" ]] || die "'$target_dir' existiert nicht. Falscher \
Repository-Klon, oder --repo-dir mitgeben."

    step "Prüfung auf Geheimnisse"
    local findings
    findings="$(scan_for_secrets "$src")"
    if [[ -n "$findings" ]]; then
        printf '%s\n' "$findings" >&2
        die "Diese Zeilen sehen aus wie ein Geheimnis. Nichts kopiert.
Ein Protokoll enthält Datum, Anwesende, Zweck, Seriennummern, Fingerprints und
den Hash des Live-Systems — mehr nicht. Zeilen prüfen, umformulieren oder
entfernen, dann erneut."
    fi
    note "Keine der bekannten Geheimnis-Formen gefunden."
    note "Das ersetzt das Lesen nicht: einmal durchsehen, es sind zwanzig Zeilen."

    step "Ablegen"
    local stamp target suffix
    stamp="$(date -u '+%Y-%m-%d')"
    target="$target_dir/protokoll-$stamp.md"
    suffix=2
    while [[ -e "$target" ]]; do
        target="$target_dir/protokoll-$stamp-$suffix.md"
        suffix=$((suffix + 1))
        # Zwei Zeremonien an einem Tag sind ungewöhnlich; deshalb sagt es der
        # Script, statt still eine zweite Datei anzulegen.
        note "Für $stamp gibt es schon ein Protokoll — dies wird $(basename "$target")."
    done
    install -m 444 "$src" "$target"
    note "$target"
    note "SHA-256: $(sha256sum "$target" | cut -d' ' -f1)"

    step "Nächster Schritt"
    note "Einchecken — das Protokoll ist der Nachweis, dass es die Zeremonie gab:"
    note "  git add $(realpath --relative-to=. "$target" 2>/dev/null || printf '%s' "$target")"
    note "  git commit -m 'docs(ca): Protokoll der Zeremonie vom $stamp'"
    note ""
    note "Das Papierprotokoll mit den Unterschriften bleibt das gültige."
    note "Diese Datei ist die durchsuchbare Kopie (Entscheid E19)."
}

# --- verify -----------------------------------------------------------------
# Die Jahreskontrolle aus Runbook §8: Stick lesbar, Prüfsummen stimmen,
# Fingerprint ist der protokollierte, Restlaufzeit im Blick.
cmd_verify() {
    require_workdir
    [[ -f "$WORKDIR/root.crt" ]] || die "root.crt nicht in $WORKDIR gefunden."

    step "Prüfsummen"
    if [[ -f "$WORKDIR/SHA256SUMS" ]]; then
        ( cd "$WORKDIR" && sha256sum -c SHA256SUMS ) || die "Prüfsummen weichen ab — Stick verdächtig."
    else
        note "Kein SHA256SUMS (Arbeitsverzeichnis statt Stick?) — übersprungen."
    fi

    step "Root-Zertifikat"
    note "Fingerprint ($DIGEST): $(fingerprint "$WORKDIR/root.crt")"
    note "Mit dem Protokoll vergleichen. Weicht er ab, ist das kein Tippfehler."
    openssl x509 -in "$WORKDIR/root.crt" -noout -dates -subject

    if [[ -f "$WORKDIR/root.key" ]]; then
        step "Schlüssel passt zum Zertifikat"
        local a b
        a="$(openssl pkey -in "$WORKDIR/root.key" -pubout -outform der | sha256sum | cut -d' ' -f1)"
        b="$(openssl x509 -in "$WORKDIR/root.crt" -pubkey -noout \
             | openssl pkey -pubin -pubout -outform der | sha256sum | cut -d' ' -f1)"
        [[ "$a" == "$b" ]] || die "Schlüssel und Zertifikat gehören nicht zusammen."
        note "Ja."
    fi

    printf '\nKontrolle abgeschlossen. Ergebnis ins Protokoll eintragen.\n'
}

# --- Argumente --------------------------------------------------------------
[[ $# -gt 0 ]] || { usage; exit 1; }
COMMAND="$1"; shift

while [[ $# -gt 0 ]]; do
    case "$1" in
        --workdir) WORKDIR="$2"; shift 2 ;;
        --device) DEVICE="$2"; shift 2 ;;
        --csr) CSR="$2"; shift 2 ;;
        --purpose) PURPOSE="$2"; shift 2 ;;
        --live-image) LIVE_IMAGE="$2"; shift 2 ;;
        --live-sha256) LIVE_SHA256="$2"; shift 2 ;;
        --file) PROTO_FILE="$2"; shift 2 ;;
        --repo-dir) REPO_DIR="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unbekannte Option: $1" ;;
    esac
done

case "$COMMAND" in
    preflight) cmd_preflight ;;
    root) cmd_root ;;
    stick) cmd_stick ;;
    intermediate) cmd_intermediate ;;
    verify) cmd_verify ;;
    protokoll) cmd_protokoll ;;
    -h|--help) usage ;;
    *) die "Unbekanntes Kommando: $COMMAND" ;;
esac
