#!/usr/bin/env bash
# install-magister.sh
#
# Idempotenter End-to-End-Installer für einen Magister-Schulträger-Host
# (Ubuntu 24.04 / Debian 12).
#
# Was es tut:
#   1. Docker + Compose installieren (falls fehlend)
#   2. Repo nach /opt/magister klonen / fast-forwarden
#   3. .env aus Template generieren (mit zufälligem MAGISTER_AUDIT_KEY)
#   4. Compose-Stack starten
#   5. Alembic-Migrationen ausführen
#   6. Smoke-Test
#
# Nicht enthalten (manuell):
#   - DNS für den FQDN setzen
#   - Entra-App-Registrierung (siehe docs/runbooks/install-ubuntu.md §3)
#   - AD-Bind-User in AD anlegen (§4)
#   - .env mit OIDC- und AD-Credentials befüllen
#
# Usage:
#   sudo ./scripts/install-magister.sh \
#       --fqdn magister.schule-x.ch \
#       --branch main

set -euo pipefail

FQDN=""
BRANCH="main"
INSTALL_DIR="/opt/magister"

usage() {
    cat <<EOF
Usage: $0 --fqdn <hostname> [--branch <git-branch>] [--dir <path>]

Options:
  --fqdn      Public DNS name (e.g. magister.schule-x.ch)  [required]
  --branch    Git branch to deploy                          [default: main]
  --dir       Install directory                             [default: /opt/magister]
  -h, --help  Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --fqdn) FQDN="$2"; shift 2 ;;
        --branch) BRANCH="$2"; shift 2 ;;
        --dir) INSTALL_DIR="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1"; usage; exit 1 ;;
    esac
done

if [[ -z "$FQDN" ]]; then
    echo "ERROR: --fqdn is required"
    usage
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: run as root (sudo)"
    exit 1
fi

log() { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }

# ---- 1. Docker -----------------------------------------------------------
log "Checking Docker installation"
if ! command -v docker >/dev/null 2>&1; then
    log "Installing Docker"
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg git ufw chrony
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable --now docker
    ok "Docker installed"
else
    ok "Docker already present: $(docker --version)"
fi

# ---- 2. Firewall ---------------------------------------------------------
log "Configuring firewall"
ufw allow 22/tcp >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ok "ufw active: 22/tcp, 80/tcp, 443/tcp open"

# ---- 3. Repo -------------------------------------------------------------
log "Fetching repo to $INSTALL_DIR"
if [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" fetch origin "$BRANCH"
    git -C "$INSTALL_DIR" checkout "$BRANCH"
    git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
else
    mkdir -p "$INSTALL_DIR"
    git clone --branch "$BRANCH" https://github.com/vita-brevis-gmbh/magister.git "$INSTALL_DIR"
fi
ok "Repo at $(git -C "$INSTALL_DIR" rev-parse --short HEAD)"

# ---- 4. .env -------------------------------------------------------------
ENV_FILE="$INSTALL_DIR/deploy/compose/.env"
if [[ -f "$ENV_FILE" ]]; then
    ok ".env already present at $ENV_FILE — leaving untouched"
else
    log "Generating .env"
    AUDIT_KEY=$(openssl rand -base64 48 | tr -d '\n')
    BOOTSTRAP_ADMIN_GUID=$(uuidgen)
    cat > "$ENV_FILE" <<EOF
# --- generated $(date -Iseconds) by install-magister.sh ---
MAGISTER_DATABASE_URL=postgresql+asyncpg://magister:magister@postgres:5432/magister
MAGISTER_AUDIT_KEY=$AUDIT_KEY
MAGISTER_AUDIT_KEY_ID=v1
MAGISTER_BOOTSTRAP_ADMIN_GUID=$BOOTSTRAP_ADMIN_GUID
MAGISTER_FQDN=$FQDN

# --- TO BE FILLED IN MANUALLY ---
MAGISTER_OIDC_ISSUER=
MAGISTER_OIDC_CLIENT_ID=
MAGISTER_OIDC_CLIENT_SECRET=
MAGISTER_OIDC_REDIRECT_URI=https://$FQDN/auth/callback

MAGISTER_AD_USE_MOCK=true
MAGISTER_AD_BIND_DN=
MAGISTER_AD_BIND_PASSWORD=
MAGISTER_AD_USERS_SEARCH_BASE=
EOF
    chmod 600 "$ENV_FILE"
    ok "Wrote $ENV_FILE — Audit-Key generated, OIDC/AD MUST be filled in before login works"
    echo ""
    echo "  ⚠ Audit-Key ist im .env. Sofort in 1Password sichern!"
    echo ""
fi

# ---- 5. Compose ----------------------------------------------------------
log "Starting Compose stack"
cd "$INSTALL_DIR/deploy/compose"
docker compose pull
docker compose up -d
sleep 5

# ---- 6. Migrations -------------------------------------------------------
log "Running Alembic migrations"
docker compose exec -T api alembic upgrade head

# ---- 7. Smoke ------------------------------------------------------------
log "Smoke-testing"
for i in {1..10}; do
    if curl -sf http://localhost:8000/healthz >/dev/null 2>&1; then
        ok "API responding"
        break
    fi
    sleep 2
done
curl -sf http://localhost:8000/healthz | tee /dev/null

cat <<EOF

────────────────────────────────────────────────────────────
✓ Magister-Foundation läuft.
  FQDN:        $FQDN
  Install-Dir: $INSTALL_DIR
  Compose:     $INSTALL_DIR/deploy/compose

Nächste Schritte:
  1. .env editieren ($ENV_FILE):
     - MAGISTER_OIDC_* aus Entra-App-Registrierung
     - MAGISTER_AD_* aus AD-Bind-User (oder ad_use_mock=true für Demo)
  2. docker compose up -d  → restart mit neuen Secrets
  3. https://$FQDN aufrufen (Caddy macht TLS via ACME)
  4. Im Cockpit registrieren:
     POST /api/instances { "slug": "...", "base_url": "https://$FQDN" }
────────────────────────────────────────────────────────────
EOF
