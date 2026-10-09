#!/usr/bin/env bash
# Einen nackten Ubuntu-Server (26.04 LTS) für die Magister-Plattform vorbereiten.
#
#   sudo ./scripts/prod-host-vorbereiten.sh --benutzer magister
#   sudo ./scripts/prod-host-vorbereiten.sh --nur-pruefen   # nichts ändern, nur prüfen
#
# Danach: ./scripts/plattform-aufbau.sh up --art prod …  (docs/runbooks/prod-installation.md)
#
# Was es tut — und nur das:
#   1. System aktualisieren, Grundwerkzeuge (git, openssl, curl, python3, age,
#      chrony, util-linux für `script`).
#   2. Docker Engine mit compose- und buildx-Plugin aus dem Docker-Repository.
#      Kennt das Repository die Ubuntu-Fassung noch nicht, die Pakete aus Ubuntu
#      (docker.io, docker-compose-v2).
#   3. Docker-Protokolle begrenzen (sonst füllt ein gesprächiger Container die
#      Platte), `live-restore`, damit ein Docker-Update die Container nicht anhält.
#   4. Automatische Sicherheitsupdates, Zeitzone Europe/Zurich, Zeitabgleich.
#   5. Den Betriebsbenutzer in die Gruppe docker, /opt/magister für ihn.
#   6. Prüfen, was der Aufbau braucht: freie Ports 80/443, ausgehende
#      Verbindungen zu Registries, Let's Encrypt, Entra und GitHub.
#
# Was es NICHT tut: Firewall der DMZ, DNS, Zertifikate, Konsole, Kunden.
# Das steht im Runbook — es sind Entscheidungen, keine Handgriffe.

set -euo pipefail

BENUTZER=""
NUR_PRUEFEN=0
ZIEL_DIR="/opt/magister"

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m  ok  \033[0m%s\n' "$*"; }
warn() { printf '\033[33m !  %s\033[0m\n' "$*"; WARNUNGEN=$((WARNUNGEN + 1)); }
die()  { printf '\033[31m !! %s\033[0m\n' "$*" >&2; exit 1; }
WARNUNGEN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --benutzer)    BENUTZER="$2"; shift 2 ;;
    --nur-pruefen) NUR_PRUEFEN=1; shift ;;
    --ziel)        ZIEL_DIR="$2"; shift 2 ;;
    -h|--help)     sed -n '2,24p' "$0"; exit 0 ;;
    *) die "Unbekannte Option: $1 (--benutzer NAME, --nur-pruefen, --ziel DIR)" ;;
  esac
done

# --- Prüfungen (auch mit --nur-pruefen) ---------------------------------------

betriebssystem_pruefen() {
  say "Betriebssystem"
  [ -r /etc/os-release ] || die "/etc/os-release fehlt — kein Ubuntu?"
  # shellcheck disable=SC1091
  . /etc/os-release
  if [ "${ID:-}" != "ubuntu" ]; then
    warn "Kein Ubuntu (${PRETTY_NAME:-?}). Geprüft ist der Aufbau auf Ubuntu 24.04 und 26.04."
  elif [ "${VERSION_ID%%.*}" -lt 24 ]; then
    die "Ubuntu ${VERSION_ID} ist zu alt — 24.04 oder 26.04 verwenden."
  else
    ok "${PRETTY_NAME} (${VERSION_CODENAME})"
  fi
  local ram_mb disk_gb
  ram_mb="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)"
  disk_gb="$(df -BG --output=avail / | tail -1 | tr -dc '0-9')"
  [ "$ram_mb" -ge 7000 ] && ok "Arbeitsspeicher ${ram_mb} MB" \
    || warn "Arbeitsspeicher ${ram_mb} MB — empfohlen sind mindestens 8 GB (Bau der Abbilder)."
  [ "$disk_gb" -ge 40 ] && ok "Freier Platz auf / ${disk_gb} GB" \
    || warn "Nur ${disk_gb} GB frei auf / — empfohlen sind 80 GB (Abbilder, Datenbank, Sicherungen)."
}

ports_pruefen() {
  say "Ports 80 und 443 (Kundenseiten)"
  local port besitzer
  for port in 80 443; do
    if [ -z "$(ss -ltnH "sport = :$port" 2>/dev/null)" ]; then
      ok "Port $port frei"
      continue
    fi
    # Den Besitzer zeigt ss nur root; ohne heisst es „belegt, von wem auch immer".
    besitzer="$(ss -ltnpH "sport = :$port" 2>/dev/null | grep -o 'users:(([^)]*' | head -1 | sed 's/users:((//' || true)"
    if [ -z "$besitzer" ]; then
      warn "Port $port ist belegt (Besitzer sieht nur root: sudo $0 --nur-pruefen)"
    else
      case "$besitzer" in
        *docker-proxy*) ok "Port $port gehört Docker (der Stack läuft schon)" ;;
        *) warn "Port $port belegt von $besitzer — Caddy der Plattform bekäme ihn nicht. Den Dienst entfernen (z. B. apt purge apache2 nginx caddy)." ;;
      esac
    fi
  done
}

ausgehend_pruefen() {
  say "Ausgehende Verbindungen (HTTPS)"
  # Was beim Aufbau und im Betrieb gebraucht wird, und wofür. Ein Proxy in der
  # DMZ wird über HTTPS_PROXY berücksichtigt (curl liest ihn selbst).
  local ziel zweck
  while IFS='|' read -r ziel zweck; do
    if curl -sS -o /dev/null --max-time 10 "https://$ziel" 2>/dev/null; then
      ok "$ziel — $zweck"
    else
      warn "$ziel nicht erreichbar — $zweck"
    fi
  done <<'ZIELE'
download.docker.com|Docker-Pakete
registry-1.docker.io|Basis-Abbilder (postgres, caddy, node, python)
ghcr.io|Abbilder aus der CI (nur mit --ziehen)
github.com|Repository und Agenten-MSI (agentenpakete.sh)
pypi.org|Python-Abhängigkeiten beim Bau der Abbilder
registry.npmjs.org|Oberflächen beim Bau der Abbilder
acme-v02.api.letsencrypt.org/directory|Zertifikate der Kundenseiten (Let's Encrypt)
login.microsoftonline.com|Anmeldung der Kunden über Entra ID
ZIELE
}

docker_pruefen() {
  say "Docker"
  if ! command -v docker >/dev/null; then
    warn "Docker fehlt"
    return 0
  fi
  ok "$(docker --version)"
  docker compose version >/dev/null 2>&1 && ok "$(docker compose version)" \
    || warn "compose-Plugin fehlt (docker compose)"
  docker buildx version >/dev/null 2>&1 && ok "buildx vorhanden" \
    || warn "buildx fehlt — der Bau der Abbilder geht dann langsamer oder gar nicht"
  systemctl is-active --quiet docker && ok "Docker-Dienst läuft" || warn "Docker-Dienst läuft nicht"
}

# --- Einrichtung --------------------------------------------------------------

grundpakete() {
  say "System aktualisieren und Grundwerkzeuge installieren"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q
  apt-get -y -q full-upgrade
  apt-get -y -q install ca-certificates curl gnupg git openssl python3 age jq \
    chrony unattended-upgrades util-linux iproute2
}

docker_installieren() {
  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    say "Docker ist bereits installiert"
    return 0
  fi
  # shellcheck disable=SC1091
  . /etc/os-release
  local repo="https://download.docker.com/linux/ubuntu"
  if curl -fsS --max-time 15 -o /dev/null "$repo/dists/${VERSION_CODENAME}/Release"; then
    say "Docker Engine aus dem Docker-Repository (${VERSION_CODENAME})"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "$repo/gpg" -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] %s %s stable\n' \
      "$(dpkg --print-architecture)" "$repo" "$VERSION_CODENAME" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -q
    apt-get -y -q install docker-ce docker-ce-cli containerd.io \
      docker-buildx-plugin docker-compose-plugin
  else
    say "Docker-Repository kennt ${VERSION_CODENAME} nicht — Pakete aus Ubuntu"
    apt-get -y -q install docker.io docker-compose-v2 docker-buildx
  fi
}

docker_einstellen() {
  local datei=/etc/docker/daemon.json
  mkdir -p /etc/docker
  if [ -s "$datei" ]; then
    warn "$datei besteht schon — nicht überschrieben. Empfohlen: log-opts max-size/max-file, live-restore."
  else
    say "Docker: Protokolle begrenzen, live-restore"
    cat > "$datei" <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "5" },
  "live-restore": true
}
JSON
  fi
  systemctl enable --now docker
  systemctl restart docker
}

system_einstellen() {
  say "Automatische Sicherheitsupdates, Zeitzone, Zeitabgleich"
  cat > /etc/apt/apt.conf.d/20auto-upgrades <<'APT'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT
  # Kein automatischer Neustart: die Plattform startet nach einem Neustart von
  # selbst (restart: unless-stopped), aber den Zeitpunkt wählt der Betrieb.
  timedatectl set-timezone Europe/Zurich 2>/dev/null || warn "Zeitzone nicht gesetzt"
  systemctl enable --now chrony >/dev/null 2>&1 || warn "chrony nicht gestartet"
  # Das Debian-Paket caddy startet eine Begrüssungsseite auf :80 — und ist
  # nach einem Neustart schneller als der Container.
  if systemctl list-unit-files caddy.service >/dev/null 2>&1 \
     && systemctl is-enabled --quiet caddy 2>/dev/null; then
    warn "Systemdienst caddy ist aktiv — er hält Port 80. Abschalten: systemctl disable --now caddy"
  fi
}

benutzer_einrichten() {
  mkdir -p "$ZIEL_DIR"
  if [ -z "$BENUTZER" ]; then
    warn "Kein --benutzer angegeben — $ZIEL_DIR gehört root, der Aufbau läuft dann mit sudo."
    return 0
  fi
  id "$BENUTZER" >/dev/null 2>&1 || die "Benutzer $BENUTZER gibt es nicht (adduser $BENUTZER)."
  say "Benutzer $BENUTZER: Gruppe docker, Besitzer von $ZIEL_DIR"
  usermod -aG docker "$BENUTZER"
  chown -R "$BENUTZER:$BENUTZER" "$ZIEL_DIR"
  # Die Gruppe docker ist root-gleich. Wer darin ist, kann jeden Container mit
  # dem Host-Dateisystem starten — nur Betriebsleute gehören hinein.
  warn "Gruppe docker gilt erst nach neuer Anmeldung von $BENUTZER (abmelden, wieder anmelden)."
}

# --- Ablauf -------------------------------------------------------------------

betriebssystem_pruefen
if [ "$NUR_PRUEFEN" -eq 0 ]; then
  [ "$(id -u)" -eq 0 ] || die "Das braucht root: sudo $0 (oder --nur-pruefen)"
  grundpakete
  docker_installieren
  docker_einstellen
  system_einstellen
  benutzer_einrichten
fi

docker_pruefen
ports_pruefen
ausgehend_pruefen

printf '\n'
if [ "$WARNUNGEN" -gt 0 ]; then
  printf '\033[33m%d Hinweis(e) oben — vor dem Aufbau ansehen.\033[0m\n' "$WARNUNGEN"
else
  printf '\033[32mHost bereit.\033[0m\n'
fi
cat <<EOF

Weiter (als ${BENUTZER:-Betriebsbenutzer}, nach neuer Anmeldung):
  cd $ZIEL_DIR
  ./scripts/plattform-aufbau.sh up --art prod \\
    --domaene mgmt.vitabrevis.ch --bind <private IP> \\
    --zusatzname mgmt.int.vitabrevis.ch --acme-mail <kontakt@…>

Runbook: docs/runbooks/prod-installation.md
EOF
