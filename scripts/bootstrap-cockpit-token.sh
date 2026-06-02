#!/usr/bin/env bash
# bootstrap-cockpit-token.sh
#
# Erzeugt einen rotierbaren Service-Token via Bootstrap-Token. Der ausgegebene
# Token wird nur einmal angezeigt — sofort in 1Password speichern.
#
# Usage:
#   ./scripts/bootstrap-cockpit-token.sh \
#       --url http://localhost:8001 \
#       --bootstrap-token "<bootstrap-token>" \
#       --description "ops-team-default" \
#       --ttl-days 90

set -euo pipefail

URL="http://localhost:8001"
BOOTSTRAP_TOKEN=""
DESCRIPTION="cockpit-default"
TTL_DAYS=90

usage() {
    cat <<EOF
Usage: $0 --bootstrap-token <token> [options]

Required:
  --bootstrap-token <token>   Bootstrap-Token aus dem .env / 1Password

Options:
  --url <url>                 Cockpit-API-Basis-URL    [default: http://localhost:8001]
  --description <text>        Token-Beschreibung        [default: cockpit-default]
  --ttl-days <n>              Gültigkeit in Tagen       [default: 90, max 365]
  -h, --help                  Help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --url) URL="$2"; shift 2 ;;
        --bootstrap-token) BOOTSTRAP_TOKEN="$2"; shift 2 ;;
        --description) DESCRIPTION="$2"; shift 2 ;;
        --ttl-days) TTL_DAYS="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1"; usage; exit 1 ;;
    esac
done

if [[ -z "$BOOTSTRAP_TOKEN" ]]; then
    echo "ERROR: --bootstrap-token is required"
    usage
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq is required (apt install jq)"
    exit 1
fi

RESPONSE=$(curl -sfS -X POST "$URL/api/service-tokens" \
    -H "Authorization: Bearer $BOOTSTRAP_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"description\": \"$DESCRIPTION\", \"ttl_days\": $TTL_DAYS}")

TOKEN=$(echo "$RESPONSE" | jq -r '.token')
TOKEN_ID=$(echo "$RESPONSE" | jq -r '.id')
EXPIRES=$(echo "$RESPONSE" | jq -r '.expires_at')

cat <<EOF

────────────────────────────────────────────────────────────
✓ Service-Token created
  ID:           $TOKEN_ID
  Description:  $DESCRIPTION
  Expires:      $EXPIRES

  ⚠ Wird nur EINMAL angezeigt. Sofort in 1Password speichern:

      $TOKEN

  Verwendung:
      curl -H "Authorization: Bearer $TOKEN" $URL/api/instances
────────────────────────────────────────────────────────────
EOF
