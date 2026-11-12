#!/usr/bin/env bash
# Tägliche Sicherung aller aktiven Kunden (ADR-0016 D1, Ebene 2).
#
# Läuft auf dem ANWENDUNGSSERVER. Das genügt, weil Sichern nur den
# *öffentlichen* age-Schlüssel braucht — Prüfen und Wiederherstellen brauchen
# den privaten und laufen deshalb auf dem Backup-Host (verify-all.sh).
#
# Die Kundenliste kommt aus der Registry-Auskunft der Konsole. Sie enthält
# bewusst keine DSN, nur Verweise (ADR-0013 D4): ein Abruf gibt niemandem
# Datenbankzugang.
#
# Rückgabewert: 0, wenn jeder Kunde eine geschriebene Sicherung hat, sonst die
# Anzahl der gescheiterten. Für den Cron heisst das: Post genau dann, wenn
# etwas fehlt.
#
# Erwartete Umgebung (z. B. aus /etc/magister/ops.env):
#   COCKPIT_URL                  https://10.0.0.5:4444
#   COCKPIT_BOOTSTRAP_TOKEN      Token für die Konsolen-API
#   COCKPIT_MANAGEMENT_MARKER    Marker des Management-Listeners (ADR-0015 D1)
#   COCKPIT_CLIENT_CERT/_KEY     Operator-Zertifikat für den Listener
#   COCKPIT_CA_BUNDLE            CA der Plattform (optional)
set -uo pipefail

: "${COCKPIT_URL:?COCKPIT_URL fehlt}"
: "${COCKPIT_BOOTSTRAP_TOKEN:?COCKPIT_BOOTSTRAP_TOKEN fehlt}"
: "${COCKPIT_MANAGEMENT_MARKER:?COCKPIT_MANAGEMENT_MARKER fehlt}"
KIND="${1:-daily}"

curl_args=(
    --silent --show-error --fail-with-body
    --max-time 900
    -H "Authorization: Bearer ${COCKPIT_BOOTSTRAP_TOKEN}"
    -H "X-Magister-Management: ${COCKPIT_MANAGEMENT_MARKER}"
)
[[ -n "${COCKPIT_CLIENT_CERT:-}" ]] && curl_args+=(--cert "$COCKPIT_CLIENT_CERT")
[[ -n "${COCKPIT_CLIENT_KEY:-}" ]] && curl_args+=(--key "$COCKPIT_CLIENT_KEY")
[[ -n "${COCKPIT_CA_BUNDLE:-}" ]] && curl_args+=(--cacert "$COCKPIT_CA_BUNDLE")

registry=$(curl "${curl_args[@]}" "${COCKPIT_URL}/api/tenants/registry") || {
    echo "[backup-all] FEHLER: Registry nicht abrufbar. Nichts gesichert." >&2
    exit 2
}

# Nur aktive Kunden: provisioning und offboarding sind Übergänge, in denen ein
# Dump einen halben Zustand festhält. Ein gesperrter Kunde wird sehr wohl
# gesichert — seine Daten sind da und sollen es bleiben.
mapfile -t rows < <(echo "$registry" | jq -r '.[] | select(.status=="active" or .status=="suspended") | "\(.id)\t\(.slug)"')

if [[ ${#rows[@]} -eq 0 ]]; then
    echo "[backup-all] WARNUNG: kein Kunde in der Registry." >&2
    exit 2
fi

failed=0
for row in "${rows[@]}"; do
    id="${row%%$'\t'*}"
    slug="${row##*$'\t'}"
    body=$(curl "${curl_args[@]}" -H 'Content-Type: application/json' \
        -d "{\"kind\":\"${KIND}\"}" \
        "${COCKPIT_URL}/api/tenants/${id}/backups") || {
        echo "[backup-all] ${slug}: Aufruf gescheitert" >&2
        failed=$((failed + 1))
        continue
    }
    # Der Endpunkt antwortet auch bei einem Fehlschlag mit 201 und trägt den
    # Grund im Feld — zu prüfen ist also der Status, nicht der HTTP-Code.
    status=$(echo "$body" | jq -r '.status')
    if [[ "$status" != "written" ]]; then
        echo "[backup-all] ${slug}: ${status} — $(echo "$body" | jq -r '.error // "ohne Grund"')" >&2
        failed=$((failed + 1))
        continue
    fi
    size=$(echo "$body" | jq -r '.size_bytes')
    echo "[backup-all] ${slug}: ok (${size} Bytes)"
done

if [[ $failed -gt 0 ]]; then
    echo "[backup-all] ${failed} von ${#rows[@]} Sicherungen gescheitert." >&2
    exit "$failed"
fi
echo "[backup-all] ${#rows[@]} Sicherungen geschrieben."
