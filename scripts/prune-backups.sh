#!/usr/bin/env bash
# Alte Kunden-Sicherungen entfernen (ADR-0016 D2, D3, E14, E15).
#
#     prune-backups.sh /mnt/magister-backup            # zeigt nur, was wegkäme
#     prune-backups.sh --apply /mnt/magister-backup    # löscht
#
# **Dieses Skript gehört auf den FILESERVER, nicht auf den Anwendungsserver.**
# Das ist keine Stilfrage. Das Dienstkonto, mit dem Magister die Dumps
# schreibt, hat auf dem Share ausdrücklich KEIN Löschrecht — damit ein
# übernommener Anwendungsserver die Sicherungen nicht mitnehmen kann
# (ADR-0016 D2). Läge dieses Skript dort und liefe mit einem Konto, das löschen
# darf, wäre genau diese Eigenschaft aufgehoben.
#
# **Warum es dieses Skript überhaupt gibt und kein `find -mtime +10 -delete`.**
# Seit E15 gibt es zwei Klassen von Sicherung im selben Verzeichnis:
#
#   *-daily.dump.age          10 Tage        (E14)
#   *-monthly.dump.age        die letzten 12 (E15)
#   *-pre_migration.dump.age  30 Tage        (D6)
#   *-manual.dump.age         10 Tage
#   *-offboarding.dump.age    10 Tage
#
# Ein `find -mtime +10 -delete` würde die Monatskopien mitnehmen — also genau
# die Dateien, die für „ein Fehler, der erst am Quartalsende auffällt" da sind.
# Der Fehler wäre still: die Sicherungen sähen weiter vollständig aus, weil die
# täglichen ja da sind, und die Lücke fiele erst auf, wenn jemand ein halbes
# Jahr zurück will.
#
# **Der Sonderfall Offboarding.** Liegt im Kundenverzeichnis eine `.offboarding`
# (von der Konsole geschrieben), gilt die KURZE Frist für alles — auch für die
# Monatskopien. Ohne das wäre die Löschzusage aus D8 unwahr: „zehn Tage nach
# dem Crypto-Shredding ist auch der Rest weg", während eine Monatskopie von
# vor elf Monaten noch daliegt.
#
# **Trockenlauf ist die Vorgabe.** Löschen von Sicherungen ist die Operation,
# bei der man sehen will, was passiert, bevor es passiert.
set -uo pipefail

APPLY=0
if [[ "${1:-}" == "--apply" ]]; then
    APPLY=1
    shift
fi

ROOT="${1:-}"
if [[ -z "$ROOT" ]]; then
    echo "Aufruf: $(basename "$0") [--apply] <share-wurzel>" >&2
    exit 2
fi

# Vorgabewerte aus E14, E15 und D6. Je Kunde überschrieben durch die
# .retention, die die Konsole neben die Dumps schreibt — ohne sie müsste
# dieses Skript die Fristen raten, und ein Kunde mit 30 Tagen Zusage, dessen
# Dumps nach 10 gelöscht werden, ist ein Vertragsbruch, den niemand bemerkt.
DEFAULT_RETENTION_DAYS=10
DEFAULT_PRE_MIGRATION_DAYS=30
DEFAULT_MONTHLY_KEEP=12

# --- Sicherungen gegen den Unfall ----------------------------------------
case "$ROOT" in
    "" | "/" | "/*" | "." | "..")
        echo "FEHLER: '$ROOT' ist keine Share-Wurzel." >&2
        exit 2
        ;;
esac
ROOT="${ROOT%/}"
if [[ ! -d "$ROOT" ]]; then
    echo "FEHLER: $ROOT ist kein Verzeichnis." >&2
    exit 2
fi
# Sieht das überhaupt wie ein Magister-Share aus? Ein falscher Pfad in einer
# Cron-Zeile ist der wahrscheinlichste Weg, mit diesem Skript Schaden
# anzurichten.
if ! compgen -G "$ROOT/*/*.dump.age" >/dev/null; then
    echo "FEHLER: unter $ROOT liegt kein einziges *.dump.age." >&2
    echo "Das sieht nicht nach dem Backup-Share aus. Abbruch." >&2
    exit 2
fi

now=$(date +%s)
total_deleted=0
total_kept=0
total_bytes=0

log() { printf '%s\n' "$*"; }

remove() {
    local file="$1" why="$2"
    local size
    size=$(stat -c %s "$file" 2>/dev/null || echo 0)
    if [[ $APPLY -eq 1 ]]; then
        if rm -f -- "$file"; then
            log "  gelöscht  $(basename "$file")  ($why)"
            total_deleted=$((total_deleted + 1))
            total_bytes=$((total_bytes + size))
        else
            log "  FEHLER beim Löschen von $file" >&2
        fi
    else
        log "  würde weg $(basename "$file")  ($why)"
        total_deleted=$((total_deleted + 1))
        total_bytes=$((total_bytes + size))
    fi
}

age_days() {
    local file="$1" mtime
    mtime=$(stat -c %Y "$file" 2>/dev/null || echo "$now")
    echo $(((now - mtime) / 86400))
}

for dir in "$ROOT"/*/; do
    [[ -d "$dir" ]] || continue
    slug=$(basename "$dir")

    retention=$DEFAULT_RETENTION_DAYS
    pre_migration=$DEFAULT_PRE_MIGRATION_DAYS
    monthly_keep=$DEFAULT_MONTHLY_KEEP
    source_note="Vorgabewerte"

    if [[ -r "$dir/.retention" ]]; then
        # Nur die drei erwarteten Schlüssel lesen, und nur Zahlen. Die Datei
        # kommt vom Anwendungsserver; `source` darauf wäre eine Einladung.
        while IFS='=' read -r key value; do
            [[ "$value" =~ ^[0-9]+$ ]] || continue
            case "$key" in
                retention_days) retention="$value" ;;
                pre_migration_retention_days) pre_migration="$value" ;;
                monthly_keep) monthly_keep="$value" ;;
            esac
        done < "$dir/.retention"
        source_note=".retention"
    fi

    offboarded=0
    if [[ -e "$dir/.offboarding" ]]; then
        offboarded=1
        # Kurze Frist für ALLES, auch für die Monatskopien.
        monthly_keep=0
        pre_migration=$retention
        source_note="$source_note + Offboarding"
    fi

    log "$slug  (Fristen: $source_note; täglich ${retention}d, vor-Migration ${pre_migration}d, Monatskopien ${monthly_keep})"

    # --- alles außer Monatskopien: nach Alter ----------------------------
    for file in "$dir"*.dump.age; do
        [[ -e "$file" ]] || continue
        case "$(basename "$file")" in
            *-monthly.dump.age) continue ;;
            *-pre_migration.dump.age) limit=$pre_migration ;;
            *) limit=$retention ;;
        esac
        days=$(age_days "$file")
        if [[ $days -gt $limit ]]; then
            remove "$file" "${days}d alt, Frist ${limit}d"
        else
            total_kept=$((total_kept + 1))
        fi
    done

    # --- Monatskopien: nach Anzahl, jüngste behalten ---------------------
    #
    # Nach Anzahl und nicht nach Alter: „die letzten zwölf" hat keine Kanten
    # am 31. und braucht keine Monatsarithmetik. Sortiert wird über den
    # Dateinamen, weil der Zeitstempel darin ISO-artig ist
    # (<slug>-YYYYMMDDTHHMMSSZ-monthly.dump.age) und damit lexikografisch
    # dasselbe wie chronologisch — verlässlicher als mtime, die ein Kopieren
    # des Shares verändert.
    mapfile -t monthlies < <(compgen -G "$dir*-monthly.dump.age" 2>/dev/null | sort -r || true)
    if [[ ${#monthlies[@]} -gt 0 ]]; then
        index=0
        for file in "${monthlies[@]}"; do
            if [[ $index -lt $monthly_keep ]]; then
                total_kept=$((total_kept + 1))
            elif [[ $offboarded -eq 1 ]]; then
                remove "$file" "Kunde offboardet, kurze Frist"
            else
                remove "$file" "Monatskopie Nr. $((index + 1)) von ${#monthlies[@]}, behalten werden $monthly_keep"
            fi
            index=$((index + 1))
        done
    fi

    # Halbe Dateien aus abgebrochenen Läufen. Älter als einen Tag heisst: der
    # Lauf ist nicht mehr unterwegs.
    for file in "$dir"*.partial; do
        [[ -e "$file" ]] || continue
        [[ $(age_days "$file") -ge 1 ]] && remove "$file" "abgebrochener Lauf"
    done
done

log ""
if [[ $APPLY -eq 1 ]]; then
    log "Gelöscht: $total_deleted Datei(en), $((total_bytes / 1024 / 1024)) MiB. Behalten: $total_kept."
else
    log "Trockenlauf. Weg wären: $total_deleted Datei(en), $((total_bytes / 1024 / 1024)) MiB. Behalten: $total_kept."
    log "Mit --apply wird gelöscht."
fi
