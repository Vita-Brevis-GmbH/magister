#!/usr/bin/env bash
# install-magister.sh — interaktiver End-to-End-Installer für einen
# Magister-Schulträger-Host (Ubuntu 24.04 / Debian 12).
#
# Bringt eine Instanz von einem nackten Docker-Host bis zur laufenden,
# einlogbaren App: erzeugt die Secrets, hasht das Break-Glass-Admin-Passwort,
# schreibt eine korrekte .env (chmod 600) und startet den Compose-Stack.
#
# Was NICHT automatisierbar ist (extern, wird am Ende als Anleitung gedruckt):
#   - DNS-A/AAAA-Record für den FQDN (Prod: Caddy braucht ihn für ACME)
#   - Entra-App-Registrierung (OIDC) und AD-Bind-User
#   - Schulen + SMI-Rollen (bis zur M2-UI noch manuelles SQL)
#
# Usage:
#   sudo ./scripts/install-magister.sh --mode prod
#   sudo ./scripts/install-magister.sh --mode dev            # HTTP, per IP erreichbar
#   ./scripts/install-magister.sh --mode dev --config-only   # nur .env schreiben
#
# Flags:
#   --mode prod|dev   prod = HTTPS/FQDN/ACME; dev = HTTP/IP/localhost   [default: prod]
#   --config-only     nur .env erzeugen, weder pullen noch starten
#   --no-up           .env (+ ggf. Docker/Repo) vorbereiten, aber nicht starten
#   --with-oidc       OIDC-Werte (Entra) abfragen und als First-Boot-Seed setzen
#   --with-ad         AD-Bind-Werte abfragen und als First-Boot-Seed setzen
#   --image-tag TAG   API- und Web-Image auf diesen Release-Tag pinnen (z.B. v0.1.1)
#   --force           bestehende NICHT-Secret-Felder in .env überschreiben
#                     (Secrets werden NIE überschrieben)
#   -h, --help        diese Hilfe

set -euo pipefail

# --- defaults --------------------------------------------------------------
MODE="prod"
CONFIG_ONLY=0
NO_UP=0
WITH_OIDC=0
WITH_AD=0
FORCE=0
IMAGE_TAG=""
DEFAULT_API_IMAGE="ghcr.io/vita-brevis-gmbh/magister-api:latest"
DEFAULT_WEB_IMAGE="ghcr.io/vita-brevis-gmbh/magister-web:latest"

usage() {
    cat <<'EOF'
install-magister.sh — interaktiver End-to-End-Installer für eine Magister-Instanz.

Usage:
  sudo ./scripts/install-magister.sh --mode prod
  sudo ./scripts/install-magister.sh --mode dev
       ./scripts/install-magister.sh --mode dev --config-only

Flags:
  --mode prod|dev   prod = HTTPS/FQDN/ACME; dev = HTTP/IP/localhost   [default: prod]
  --config-only     nur .env erzeugen, weder pullen noch starten
  --no-up           vorbereiten + Images ziehen, aber nicht starten
  --with-oidc       OIDC-Werte (Entra) abfragen (First-Boot-Seed)
  --with-ad         AD-Bind-Werte abfragen (First-Boot-Seed)
  --image-tag TAG   API- und Web-Image auf einen Release-Tag pinnen
  --force           bestehende NICHT-Secret-Felder überschreiben (Secrets nie)
  -h, --help        diese Hilfe
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode) MODE="${2:-}"; shift 2 ;;
        --config-only) CONFIG_ONLY=1; shift ;;
        --no-up) NO_UP=1; shift ;;
        --with-oidc) WITH_OIDC=1; shift ;;
        --with-ad) WITH_AD=1; shift ;;
        --image-tag) IMAGE_TAG="${2:-}"; shift 2 ;;
        --force) FORCE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unbekanntes Argument: $1" >&2; usage; exit 1 ;;
    esac
done

if [[ "$MODE" != "prod" && "$MODE" != "dev" ]]; then
    echo "ERROR: --mode muss 'prod' oder 'dev' sein (war: '$MODE')" >&2
    exit 1
fi

# --- pretty output ---------------------------------------------------------
log()  { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠ %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# --- locate the repo we live in -------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
    :
else
    die "Dieses Script muss aus einem Magister-Repo-Checkout laufen (git clone … && cd magister)."
fi
COMPOSE_DIR="$REPO_ROOT/deploy/compose"
ENV_FILE="$COMPOSE_DIR/.env"
[[ -f "$COMPOSE_DIR/docker-compose.yml" ]] || die "docker-compose.yml nicht gefunden unter $COMPOSE_DIR"

# compose-Datei-Set je Modus (relative Namen; alle compose-Aufrufe laufen aus
# $COMPOSE_DIR, wo auch die .env liegt und automatisch gelesen wird).
COMPOSE_ARGS=(-f docker-compose.yml)
if [[ "$MODE" == "dev" ]]; then
    [[ -f "$COMPOSE_DIR/docker-compose.dev.yml" ]] || die "docker-compose.dev.yml fehlt — Branch zu alt?"
    COMPOSE_ARGS+=(-f docker-compose.dev.yml)
fi
dc() { ( cd "$COMPOSE_DIR" && docker compose "${COMPOSE_ARGS[@]}" "$@" ); }

API_IMAGE="$DEFAULT_API_IMAGE"
WEB_IMAGE="$DEFAULT_WEB_IMAGE"
if [[ -n "$IMAGE_TAG" ]]; then
    API_IMAGE="ghcr.io/vita-brevis-gmbh/magister-api:${IMAGE_TAG}"
    WEB_IMAGE="ghcr.io/vita-brevis-gmbh/magister-web:${IMAGE_TAG}"
fi

# --- preflight: Docker -----------------------------------------------------
ensure_docker() {
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        ok "Docker vorhanden: $(docker --version)"
        return
    fi
    if [[ $CONFIG_ONLY -eq 1 ]]; then
        warn "Docker/Compose fehlt — bei --config-only ok (zum Hashen wird es aber gebraucht)."
        return
    fi
    [[ $EUID -eq 0 ]] || die "Docker fehlt und Installation braucht root. Mit sudo erneut starten."
    log "Installiere Docker + Compose-Plugin"
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
    ok "Docker installiert"
}

ensure_firewall() {
    [[ $EUID -eq 0 ]] || return 0
    command -v ufw >/dev/null 2>&1 || return 0
    log "Firewall (ufw): 22/80/443 öffnen"
    ufw allow 22/tcp  >/dev/null 2>&1 || true
    ufw allow 80/tcp  >/dev/null 2>&1 || true
    ufw allow 443/tcp >/dev/null 2>&1 || true
    ufw --force enable >/dev/null 2>&1 || true
    ok "ufw aktiv: 22, 80, 443 offen"
}

# --- helpers: secrets + hash ----------------------------------------------
# URL-safe Token (keine + / = die .env-Parsing oder sed brechen würden).
gen_secret() {
    if command -v python3 >/dev/null 2>&1; then
        python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
    else
        docker run --rm --entrypoint python "$API_IMAGE" \
            -c 'import secrets; print(secrets.token_urlsafe(48))'
    fi
}

# Docker Compose interpoliert $ in .env-Werten. Ein literales $ (v.a. im
# argon2-Hash $argon2id$v=19$...) MUSS als $$ geschrieben werden, sonst frisst
# compose die $-Sequenzen als Variablen und der Hash kommt korrupt am Container
# an (Login schlägt dann ohne Fehlermeldung fehl). esc verdoppelt, unesc kehrt
# das beim Wiedereinlesen einer bestehenden .env um (Kanonform im Speicher).
esc()   { printf '%s' "${1//\$/\$\$}"; }
unesc() { printf '%s' "${1//\$\$/\$}"; }

# Liest einen Wert aus einer .env-Datei (erste Zeile ^KEY=...), ohne sie zu sourcen.
read_env_value() {
    local key="$1" file="$2"
    [[ -f "$file" ]] || return 1
    local line
    line="$(grep -E "^${key}=" "$file" | head -n1)" || return 1
    [[ -n "$line" ]] || return 1
    printf '%s' "${line#*=}"
}

# Liefert einen vorhandenen, „echten" Secret-Wert aus der alten .env zurück,
# sonst ein frisch generiertes — so wird MAGISTER_AUDIT_KEY nie regeneriert.
secret_preserve_or_gen() {
    local key="$1" old
    if old="$(read_env_value "$key" "$ENV_FILE" 2>/dev/null)" \
        && [[ -n "$old" && "$old" != CHANGE_ME* ]]; then
        printf '%s' "$old"
    else
        gen_secret
    fi
}

# Hasht ein Passwort (stdin) via API-Image zu argon2id. --entrypoint python
# umgeht den `alembic upgrade head`-Entrypoint. Wir importieren direkt
# auth.passwords (statt -m magister_api.cli.hash_password), damit das auch auf
# veröffentlichten Images funktioniert, die das cli-Modul noch nicht enthalten
# (z.B. ein :latest, das älter ist als dieser Commit). Die >=12-Zeichen-Regel
# ist im Installer bereits vor dem Aufruf geprüft.
hash_password_via_image() {
    local pw="$1"
    printf '%s' "$pw" | docker run --rm -i --entrypoint python "$API_IMAGE" \
        -c 'import sys; from magister_api.auth.passwords import hash_password; print(hash_password(sys.stdin.readline().rstrip("\n")))'
}

prompt_default() {  # prompt_default "Frage" "default" -> echo Antwort
    local q="$1" def="${2:-}" ans
    if [[ -n "$def" ]]; then read -rp "$q [$def]: " ans; else read -rp "$q: " ans; fi
    printf '%s' "${ans:-$def}"
}

# --- run -------------------------------------------------------------------
log "Magister-Installer — Modus: $MODE"
ensure_docker
[[ $CONFIG_ONLY -eq 0 ]] && ensure_firewall

# Idempotenz: vorhandene .env respektieren.
[[ -f "$ENV_FILE" ]] && ok "Bestehende .env gefunden — Secrets werden bewahrt."

# 1) Hostname
DEF_HOST="$(read_env_value MAGISTER_PUBLIC_HOSTNAME "$ENV_FILE" 2>/dev/null || true)"
[[ -z "$DEF_HOST" || "$DEF_HOST" == magister.example.ch ]] && DEF_HOST=""
if [[ "$MODE" == "dev" && -z "$DEF_HOST" ]]; then DEF_HOST="localhost"; fi
HOSTNAME_VALUE="$(prompt_default "Öffentlicher Hostname (Prod: FQDN; Dev: IP/localhost)" "$DEF_HOST")"
[[ -n "$HOSTNAME_VALUE" ]] || die "Hostname ist erforderlich."

# Prod: warnen wenn der Hostname nicht auflöst / eine IP ist (ACME scheitert dann).
if [[ "$MODE" == "prod" ]]; then
    if [[ "$HOSTNAME_VALUE" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ || "$HOSTNAME_VALUE" == "localhost" ]]; then
        warn "Im Prod-Modus brauchst du einen DNS-Namen — Let's Encrypt stellt für IP/localhost kein Zertifikat aus. Für Demo per IP: --mode dev."
    elif command -v getent >/dev/null 2>&1 && ! getent hosts "$HOSTNAME_VALUE" >/dev/null 2>&1; then
        warn "$HOSTNAME_VALUE löst aktuell nicht auf — ACME schlägt fehl, bis der DNS-A/AAAA-Record gesetzt ist."
    fi
fi

# 2) ACME-Mail (compose verlangt sie via :? auch im Dev-Modus)
DEF_MAIL="$(read_env_value MAGISTER_ACME_EMAIL "$ENV_FILE" 2>/dev/null || true)"
[[ -z "$DEF_MAIL" || "$DEF_MAIL" == ops@example.ch ]] && DEF_MAIL=""
ACME_EMAIL="$(prompt_default "ACME-Kontakt-Mail (Let's Encrypt; im Dev-Modus ungenutzt, aber erforderlich)" "$DEF_MAIL")"
[[ -n "$ACME_EMAIL" ]] || die "ACME-Mail ist erforderlich (compose-Pflichtfeld)."

# 3) Local-Admin
ADMIN_USER="$(prompt_default "Local-Admin-Benutzername" "$(read_env_value MAGISTER_LOCAL_ADMIN_USERNAME "$ENV_FILE" 2>/dev/null || echo admin)")"

# Auf Platte ist der Hash $$-escaped; in die Kanonform ($argon2…) zurückholen.
EXISTING_HASH="$(unesc "$(read_env_value MAGISTER_LOCAL_ADMIN_PASSWORD_HASH "$ENV_FILE" 2>/dev/null || true)")"
ADMIN_HASH=""
if [[ -n "$EXISTING_HASH" && "$EXISTING_HASH" == \$argon2* && $FORCE -eq 0 ]]; then
    ok "Bestehender Admin-Hash bleibt erhalten (mit --force neu setzen)."
    ADMIN_HASH="$EXISTING_HASH"
else
    if ! command -v docker >/dev/null 2>&1; then
        die "Zum Hashen wird Docker + das API-Image gebraucht. Ohne Docker: --config-only ist hier nicht möglich."
    fi
    while :; do
        read -rsp "Passwort für '$ADMIN_USER' (min. 12 Zeichen): " PW1; echo
        read -rsp "Passwort bestätigen: " PW2; echo
        [[ "$PW1" == "$PW2" ]]            || { warn "Passwörter stimmen nicht überein."; continue; }
        [[ "${#PW1}" -ge 12 ]]           || { warn "Mindestens 12 Zeichen."; continue; }
        break
    done
    log "Hashe Passwort via API-Image ($API_IMAGE) …"
    if ! ADMIN_HASH="$(hash_password_via_image "$PW1")"; then
        unset PW1 PW2
        die "Hashing fehlgeschlagen — ist das API-Image pullbar? ($API_IMAGE)"
    fi
    unset PW1 PW2
    [[ "$ADMIN_HASH" == \$argon2* ]] || die "Unerwartete Hash-Ausgabe — Abbruch."
    ok "Admin-Hash erzeugt."
fi

# 4) Secrets (bewahren falls vorhanden, sonst generieren)
log "Erzeuge/übernehme Secrets …"
POSTGRES_PASSWORD="$(secret_preserve_or_gen POSTGRES_PASSWORD)"
AUDIT_KEY="$(secret_preserve_or_gen MAGISTER_AUDIT_KEY)"
SESSION_SECRET="$(secret_preserve_or_gen MAGISTER_SESSION_SECRET)"
CSRF_SECRET="$(secret_preserve_or_gen MAGISTER_CSRF_SECRET)"
ok "Secrets bereit."

# 5) Optionale First-Boot-Seeds (OIDC / AD)
OIDC_ISSUER=""; OIDC_CLIENT_ID=""; OIDC_CLIENT_SECRET=""; BOOTSTRAP_ADMINS=""
if [[ $WITH_OIDC -eq 1 ]]; then
    log "OIDC (Entra) — wird nur beim allerersten Boot in die DB geseedet"
    OIDC_ISSUER="$(prompt_default "OIDC Issuer (https://login.microsoftonline.com/<tenant>/v2.0)" "")"
    OIDC_CLIENT_ID="$(prompt_default "OIDC Client-ID" "")"
    read -rsp "OIDC Client-Secret: " OIDC_CLIENT_SECRET; echo
    BOOTSTRAP_ADMINS="$(prompt_default "Bootstrap-Admin-UPNs (Komma-separiert)" "")"
fi
AD_DCS=""; AD_BIND_DN=""; AD_BIND_PASSWORD=""; AD_SEARCH_BASE=""
if [[ $WITH_AD -eq 1 ]]; then
    log "AD-Sync — wird nur beim allerersten Boot in die DB geseedet"
    AD_DCS="$(prompt_default "AD-DCs (Komma-separiert, z.B. dc1.example.local,dc2.example.local)" "")"
    AD_BIND_DN="$(prompt_default "AD-Bind-DN" "")"
    read -rsp "AD-Bind-Passwort: " AD_BIND_PASSWORD; echo
    AD_SEARCH_BASE="$(prompt_default "AD-Users-Search-Base (z.B. OU=Users,DC=example,DC=local)" "")"
fi

# 6) .env schreiben
log "Schreibe $ENV_FILE"
umask 077
# Jeder Wert wird durch esc geschützt ($ -> $$), damit compose ihn literal
# durchreicht (kritisch für den argon2-Hash und etwaige $-haltige Passwörter).
{
    echo "# --- generated $(date -Iseconds) by install-magister.sh (mode=$MODE) ---"
    echo "MAGISTER_PUBLIC_HOSTNAME=$(esc "$HOSTNAME_VALUE")"
    echo "MAGISTER_ACME_EMAIL=$(esc "$ACME_EMAIL")"
    echo "MAGISTER_LOG_LEVEL=INFO"
    if [[ -n "$IMAGE_TAG" ]]; then
        echo "MAGISTER_API_IMAGE=$(esc "$API_IMAGE")"
        echo "MAGISTER_WEB_IMAGE=$(esc "$WEB_IMAGE")"
    fi
    echo ""
    echo "# Database"
    echo "POSTGRES_USER=magister"
    echo "POSTGRES_PASSWORD=$(esc "$POSTGRES_PASSWORD")"
    echo "POSTGRES_DB=magister"
    echo ""
    echo "# Crypto / sessions — AUDIT_KEY ist ein One-Way-Door: separat sichern, NIE rotieren."
    echo "MAGISTER_AUDIT_KEY=$(esc "$AUDIT_KEY")"
    echo "MAGISTER_SESSION_SECRET=$(esc "$SESSION_SECRET")"
    echo "MAGISTER_CSRF_SECRET=$(esc "$CSRF_SECRET")"
    echo ""
    echo "# Local break-glass admin (argon2id-Hash; nur beim ersten Boot konsultiert)"
    echo "MAGISTER_LOCAL_ADMIN_USERNAME=$(esc "$ADMIN_USER")"
    echo "MAGISTER_LOCAL_ADMIN_PASSWORD_HASH=$(esc "$ADMIN_HASH")"
    if [[ $WITH_OIDC -eq 1 ]]; then
        echo ""
        echo "# OIDC (First-Boot-Seed; danach ist die DB/das GUI maßgeblich)"
        echo "MAGISTER_OIDC_ISSUER=$(esc "$OIDC_ISSUER")"
        echo "MAGISTER_OIDC_CLIENT_ID=$(esc "$OIDC_CLIENT_ID")"
        echo "MAGISTER_OIDC_CLIENT_SECRET=$(esc "$OIDC_CLIENT_SECRET")"
        echo "MAGISTER_BOOTSTRAP_ADMINS=$(esc "$BOOTSTRAP_ADMINS")"
    fi
    if [[ $WITH_AD -eq 1 ]]; then
        echo ""
        echo "# AD-Sync (First-Boot-Seed; danach ist die DB/das GUI maßgeblich)"
        echo "MAGISTER_AD_DCS=$(esc "$AD_DCS")"
        echo "MAGISTER_AD_BIND_DN=$(esc "$AD_BIND_DN")"
        echo "MAGISTER_AD_BIND_PASSWORD=$(esc "$AD_BIND_PASSWORD")"
        echo "MAGISTER_AD_USERS_SEARCH_BASE=$(esc "$AD_SEARCH_BASE")"
        echo "MAGISTER_AD_SYNC_INTERVAL_MINUTES=15"
    fi
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"
ok "$ENV_FILE geschrieben (chmod 600)."

printf '\n\033[1;33m'
cat <<'BANNER'
╔══════════════════════════════════════════════════════════════════════╗
║  MAGISTER_AUDIT_KEY ist jetzt in der .env. SICHERE IHN SEPARAT         ║
║  (Passwort-Manager), GETRENNT vom DB-Backup, und ROTIERE IHN NIE —     ║
║  sonst werden alle verschlüsselten audit_events.payload unlesbar.      ║
╚══════════════════════════════════════════════════════════════════════╝
BANNER
printf '\033[0m\n'

# 7) Validierung
log "Validiere Compose-Konfiguration"
dc config -q || die "docker compose config fehlgeschlagen — .env prüfen."
ok "Compose-Konfiguration valide."

COMPOSE_HINT="cd $COMPOSE_DIR && docker compose ${COMPOSE_ARGS[*]}"

if [[ $CONFIG_ONLY -eq 1 ]]; then
    log "--config-only: .env geschrieben, Stack nicht gestartet."
    echo "Start später mit:  $COMPOSE_HINT up -d"
    exit 0
fi

# 8) Pull + Start
log "Ziehe Images"
dc pull

if [[ $NO_UP -eq 1 ]]; then
    log "--no-up: Images gezogen, Stack nicht gestartet."
    echo "Start mit:  $COMPOSE_HINT up -d"
    exit 0
fi

log "Starte Stack"
dc up -d

# 9) Smoke-Test gegen magister-api (image-unabhängig via python stdlib)
log "Smoke-Test (/healthz)"
HEALTHY=0
for _ in $(seq 1 20); do
    if dc exec -T magister-api \
        python -c 'import urllib.request,sys; sys.exit(0 if urllib.request.urlopen("http://localhost:8000/healthz",timeout=2).status==200 else 1)' \
        >/dev/null 2>&1; then
        HEALTHY=1; break
    fi
    sleep 3
done
if [[ $HEALTHY -eq 1 ]]; then ok "API antwortet (/healthz)."; else warn "API antwortete im Zeitfenster nicht — '$COMPOSE_HINT logs magister-api' prüfen."; fi

# 10) Next steps
if [[ "$MODE" == "dev" ]]; then URL="http://$HOSTNAME_VALUE"; else URL="https://$HOSTNAME_VALUE"; fi
cat <<EOF

────────────────────────────────────────────────────────────
✓ Magister läuft ($MODE).
  URL:     $URL
  Compose: $COMPOSE_DIR

Nächste Schritte:
  1. $URL öffnen, als Local-Admin '$ADMIN_USER' einloggen.
$( [[ "$MODE" == "dev" ]] && echo "     (Dev: zwingend http://, ggf. alte Cookies für den Host löschen.)" )
  2. Im Admin-GUI OIDC (Entra), AD-Sync und Mail-Domains konfigurieren.
  3. Per Entra (SSO) re-login; Bootstrap-Admin-UPNs greifen beim ersten OIDC-Login.
  4. Schulen + SMI-Rollen anlegen (bis zur M2-UI noch via SQL — siehe Runbook).

Demo-Daten (optional):
  docker compose ${COMPOSE_ARGS[*]} exec magister-api \\
    python -m magister_api.cli.seed_demo
────────────────────────────────────────────────────────────
EOF
