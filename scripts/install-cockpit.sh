#!/usr/bin/env bash
# install-cockpit.sh
#
# Idempotenter Installer für das Vita-Brevis-Cockpit auf einem internen
# Ops-Host (Ubuntu 24.04 / Debian 12). Cockpit läuft hinter VPN/Tailscale —
# dieser Script richtet KEIN öffentliches TLS ein.
#
# Usage:
#   sudo ./scripts/install-cockpit.sh [--branch main] [--dir /opt/cockpit]

set -euo pipefail

BRANCH="main"
INSTALL_DIR="/opt/cockpit"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --branch) BRANCH="$2"; shift 2 ;;
        --dir) INSTALL_DIR="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--branch <git-branch>] [--dir <path>]"
            exit 0 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: run as root (sudo)"
    exit 1
fi

log() { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }

# ---- 1. Docker -----------------------------------------------------------
log "Checking Docker"
if ! command -v docker >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg git
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
    ok "Docker already present"
fi

# ---- 2. Repo -------------------------------------------------------------
log "Fetching repo to $INSTALL_DIR/src"
if [[ -d "$INSTALL_DIR/src/.git" ]]; then
    git -C "$INSTALL_DIR/src" fetch origin "$BRANCH"
    git -C "$INSTALL_DIR/src" checkout "$BRANCH"
    git -C "$INSTALL_DIR/src" pull --ff-only origin "$BRANCH"
else
    mkdir -p "$INSTALL_DIR"
    git clone --branch "$BRANCH" https://github.com/vita-brevis-gmbh/magister.git "$INSTALL_DIR/src"
fi
ok "Repo at $(git -C "$INSTALL_DIR/src" rev-parse --short HEAD)"

# ---- 3. .env -------------------------------------------------------------
ENV_FILE="$INSTALL_DIR/src/cockpit/deploy/.env"
if [[ -f "$ENV_FILE" ]]; then
    ok ".env already present — leaving untouched"
else
    log "Generating bootstrap-token + .env"
    BOOTSTRAP_TOKEN=$(openssl rand -base64 32 | tr -d '/+=\n' | head -c 40)
    cat > "$ENV_FILE" <<EOF
# --- generated $(date -Iseconds) by install-cockpit.sh ---
COCKPIT_BOOTSTRAP_TOKEN=$BOOTSTRAP_TOKEN
EOF
    chmod 600 "$ENV_FILE"
    ok "Wrote $ENV_FILE"
    echo ""
    echo "  ⚠ BOOTSTRAP-TOKEN — sofort in 1Password speichern:"
    echo ""
    echo "      $BOOTSTRAP_TOKEN"
    echo ""
fi

# ---- 4. Compose ----------------------------------------------------------
log "Starting cockpit stack"
cd "$INSTALL_DIR/src/cockpit/deploy"
docker compose pull
docker compose up -d
sleep 5

# ---- 5. Migrations -------------------------------------------------------
log "Running migrations"
docker compose exec -T api alembic upgrade head

# ---- 6. Smoke ------------------------------------------------------------
log "Smoke-testing"
for i in {1..15}; do
    if curl -sf http://localhost:8001/api/health >/dev/null 2>&1; then
        ok "API responding"
        break
    fi
    sleep 2
done
curl -sf http://localhost:8001/api/health

# ---- 7. Backup-Cron ------------------------------------------------------
log "Installing daily backup cron"
cat > /etc/cron.daily/cockpit-backup <<EOF
#!/bin/bash
set -e
cd $INSTALL_DIR/src/cockpit/deploy
mkdir -p /backup
docker compose exec -T postgres pg_dump -U cockpit cockpit \\
  | gzip > /backup/cockpit-\$(date +%Y%m%d).sql.gz
find /backup -name 'cockpit-*.sql.gz' -mtime +30 -delete
EOF
chmod +x /etc/cron.daily/cockpit-backup
ok "Backup-Cron installed at /etc/cron.daily/cockpit-backup"

cat <<EOF

────────────────────────────────────────────────────────────
✓ Cockpit läuft auf http://localhost:8001

Nächste Schritte:
  1. Ersten Service-Token erzeugen:
     scripts/bootstrap-cockpit-token.sh --bootstrap-token "<token>"
  2. Erste Magister-Instanz registrieren (siehe docs/runbooks/install-cockpit.md §8)
  3. (Optional) Update-Runner installieren (siehe cockpit-update-runner.md)
  4. Frontend deployen — bis es als Compose-Service drin ist:
     cd $INSTALL_DIR/src/cockpit/web && pnpm install && pnpm build
     # dist/ statisch ausliefern (z.B. via caddy oder nginx)
────────────────────────────────────────────────────────────
EOF
