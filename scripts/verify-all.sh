#!/usr/bin/env bash
# Wöchentliche Prüf-Wiederherstellung aller Kunden (ADR-0016 D4).
#
# Läuft auf dem BACKUP-HOST, weil hier der private age-Schlüssel liegt. Auf dem
# Anwendungsserver liegt er nicht — das ist die Zusage aus ADR-0016 D2, und
# deshalb ist dieses Skript hier und nicht dort.
#
# Ein Backup gilt erst als Backup, wenn es eingespielt wurde. Geprüft wird der
# jüngste Dump jedes Kunden; das Ergebnis geht an die Konsole.
#
# Rückgabewert: 0, wenn jeder Kunde eine geprüfte Sicherung hat, sonst die
# Anzahl der unbrauchbaren.
#
# Erwartete Umgebung zusätzlich zu backup-all.sh:
#   MAGISTER_BACKUP_IDENTITY   private age-Identitätsdatei
#   MAGISTER_BACKUP_SHARE      Wurzel des Shares, z. B. /mnt/magister-backup
#   MAGISTER_ADMIN_DSN         Verwaltungszugang in den Cluster (CREATEDB)
#   COCKPIT_API_DIR            Verzeichnis mit dem cockpit_api-Paket
#   MAGISTER_PSQL_DSN          optional: derselbe Cluster als libpq-URL
#                              (postgresql://…), um Referenz-Zeilenzahlen aus
#                              der Produktion zu holen. Ohne ihn entfaellt der
#                              Groessenordnungs-Vergleich — dann prueft der
#                              Lauf nur, dass der Dump einspielbar ist.
set -uo pipefail

: "${COCKPIT_URL:?COCKPIT_URL fehlt}"
: "${COCKPIT_BOOTSTRAP_TOKEN:?COCKPIT_BOOTSTRAP_TOKEN fehlt}"
: "${COCKPIT_MANAGEMENT_MARKER:?COCKPIT_MANAGEMENT_MARKER fehlt}"
: "${MAGISTER_BACKUP_IDENTITY:?MAGISTER_BACKUP_IDENTITY fehlt}"
: "${MAGISTER_BACKUP_SHARE:?MAGISTER_BACKUP_SHARE fehlt}"
: "${MAGISTER_ADMIN_DSN:?MAGISTER_ADMIN_DSN fehlt}"
: "${COCKPIT_API_DIR:=/opt/magister/cockpit/api}"

if [[ ! -r "$MAGISTER_BACKUP_IDENTITY" ]]; then
    echo "[verify-all] FEHLER: ${MAGISTER_BACKUP_IDENTITY} ist nicht lesbar." >&2
    echo "[verify-all] Ohne privaten Schlüssel ist keine Prüfung möglich — und" >&2
    echo "[verify-all] dieses Skript gehört auf den Host, wo er liegt." >&2
    exit 2
fi

curl_args=(
    --silent --show-error --fail-with-body --max-time 60
    -H "Authorization: Bearer ${COCKPIT_BOOTSTRAP_TOKEN}"
    -H "X-Magister-Management: ${COCKPIT_MANAGEMENT_MARKER}"
)
[[ -n "${COCKPIT_CLIENT_CERT:-}" ]] && curl_args+=(--cert "$COCKPIT_CLIENT_CERT")
[[ -n "${COCKPIT_CLIENT_KEY:-}" ]] && curl_args+=(--key "$COCKPIT_CLIENT_KEY")
[[ -n "${COCKPIT_CA_BUNDLE:-}" ]] && curl_args+=(--cacert "$COCKPIT_CA_BUNDLE")

registry=$(curl "${curl_args[@]}" "${COCKPIT_URL}/api/tenants/registry") || {
    echo "[verify-all] FEHLER: Registry nicht abrufbar." >&2
    exit 2
}
mapfile -t rows < <(echo "$registry" | jq -r '.[] | "\(.id)\t\(.slug)\t\(.schema_name)\t\(.schema_version // "")"')

failed=0
checked=0
for row in "${rows[@]}"; do
    IFS=$'\t' read -r id slug schema version <<<"$row"

    # Die jüngste Sicherung dieses Kunden aus der Konsole holen: sie kennt
    # Pfad, Prüfsumme und Schlüssel-Id. Vom Share zu raten wäre möglich, aber
    # dann fehlte die Prüfsumme — und die ist der halbe Zweck der Übung.
    newest=$(curl "${curl_args[@]}" "${COCKPIT_URL}/api/tenants/${id}/backups" \
        | jq -r '[.[] | select(.status=="written" or .status=="verified")] | first // empty')
    if [[ -z "$newest" ]]; then
        echo "[verify-all] ${slug}: keine geschriebene Sicherung vorhanden" >&2
        failed=$((failed + 1))
        continue
    fi
    backup_id=$(echo "$newest" | jq -r '.id')
    dump=$(echo "$newest" | jq -r '.path')
    sum=$(echo "$newest" | jq -r '.checksum_sha256 // empty')

    # Der Pfad in der Konsole ist der des Anwendungsservers. Auf diesem Host
    # kann der Share anders gemountet sein, deshalb der Dateiname unter
    # MAGISTER_BACKUP_SHARE.
    local_dump="${MAGISTER_BACKUP_SHARE}/${slug}/$(basename "$dump")"
    if [[ ! -r "$local_dump" ]]; then
        echo "[verify-all] ${slug}: ${local_dump} nicht lesbar (Mount?)" >&2
        failed=$((failed + 1))
        continue
    fi

    args=(
        --admin-dsn "$MAGISTER_ADMIN_DSN"
        --dump "$local_dump"
        --identity "$MAGISTER_BACKUP_IDENTITY"
        --slug "$slug"
        --schema "$schema"
        --console "$COCKPIT_URL"
        --backup-id "$backup_id"
    )

    # Referenz-Zeilenzahlen aus der PRODUKTION mitgeben. Ohne sie prueft die
    # Pruef-Wiederherstellung nur, dass der Dump *einspielbar* ist — ein Dump
    # mit drei statt dreihundert Schuelern spielt tadellos ein. Verglichen wird
    # auf Groessenordnung und nicht auf Gleichheit; zwischen Sicherung und
    # Pruefung liegen Tage produktiver Arbeit.
    #
    # Faellt die Abfrage aus (Cluster nicht erreichbar), laeuft die Pruefung
    # ohne diesen Punkt weiter: eine fehlende Referenz soll nicht als kaputtes
    # Backup gemeldet werden.
    if [[ -n "${MAGISTER_PSQL_DSN:-}" ]]; then
        for table in schools classes ad_user_cache; do
            count=$(psql "$MAGISTER_PSQL_DSN" -Atc \
                "SELECT count(*) FROM \"${schema}\".\"${table}\"" 2>/dev/null) || continue
            [[ "$count" =~ ^[0-9]+$ ]] && args+=(--rows "${table}=${count}")
        done
    fi
    [[ -n "$sum" ]] && args+=(--checksum "$sum")
    [[ -n "$version" ]] && args+=(--expected-schema-version "$version")
    [[ -n "${COCKPIT_CA_BUNDLE:-}" ]] && args+=(--ca-bundle "$COCKPIT_CA_BUNDLE")

    checked=$((checked + 1))
    if (cd "$COCKPIT_API_DIR" && python -m cockpit_api.cli.verify_backup "${args[@]}"); then
        echo "[verify-all] ${slug}: ok"
    else
        echo "[verify-all] ${slug}: PRÜFUNG GESCHEITERT" >&2
        failed=$((failed + 1))
    fi
done

if [[ $failed -gt 0 ]]; then
    echo "[verify-all] ${failed} Kunden ohne brauchbare Sicherung." >&2
    exit "$failed"
fi
echo "[verify-all] ${checked} Sicherungen geprüft."
