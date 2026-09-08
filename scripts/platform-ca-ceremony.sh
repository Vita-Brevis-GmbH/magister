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
# Usage:
#   ./scripts/platform-ca-ceremony.sh preflight
#   ./scripts/platform-ca-ceremony.sh root        --workdir /mnt/ceremony
#   ./scripts/platform-ca-ceremony.sh stick       --workdir /mnt/ceremony --device /dev/sdX
#   ./scripts/platform-ca-ceremony.sh intermediate --workdir /mnt/ceremony \
#         --csr connector-int.csr --purpose connector
#   ./scripts/platform-ca-ceremony.sh verify      --workdir /mnt/ceremony
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
    sed -n '3,26p' "$0" | sed 's/^# \{0,1\}//'
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
}

# --- intermediate -----------------------------------------------------------
cmd_intermediate() {
    require_workdir
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
    log_protocol "- Unterschriften: ________________  ________________"

    step "Nächster Schritt"
    note "Nur $out zurück auf den Server. Der Root-Schlüssel bleibt hier."
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
    -h|--help) usage ;;
    *) die "Unbekanntes Kommando: $COMMAND" ;;
esac
