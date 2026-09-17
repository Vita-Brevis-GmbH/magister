#!/usr/bin/env bash
# Die gehostete Magister-Plattform auf EINEM Host — so, wie sie in
# Produktion steht.
#
#   ./scripts/plattform-aufbau.sh up      # aufbauen und starten
#   ./scripts/plattform-aufbau.sh update  # dasselbe — nach einem `git pull`
#   ./scripts/plattform-aufbau.sh up --ui-neu   # Oberfläche zwingend neu bauen
#   ./scripts/plattform-aufbau.sh status  # was läuft, was antwortet
#   ./scripts/plattform-aufbau.sh konfig  # welche Angaben gelten
#   ./scripts/plattform-aufbau.sh down    # beide Stacks anhalten
#   ./scripts/plattform-aufbau.sh purge   # anhalten UND alles löschen
#
#   ./scripts/plattform-aufbau.sh operator --upn … --name … --set-password
#   ./scripts/plattform-aufbau.sh operator --upn … --reset-mfa
#   ./scripts/plattform-aufbau.sh totp --upn … --code 123456
#
# Der Unterschied zu `dev-umgebung.sh`: dort laufen die Dienste als nackte
# Prozesse auf der Maschine, damit man mit einem Breakpoint hineinkommt.
# Hier laufen genau die Container, die auch in Produktion laufen, mit
# denselben Compose-Dateien, demselben Caddy, denselben Netzen und
# denselben Pflichtwerten. Was hier scheitert, scheitert in Produktion auch
# — und das ist der ganze Zweck.
#
# Zwei Dinge sind bewusst anders als in Produktion, und nur diese zwei:
#
#   1. Die Abbilder werden hier aus dem Arbeitsstand gebaut statt aus GHCR
#      gezogen (`--ziehen` kehrt das um). Ein Stand, den es als Abbild noch
#      nicht gibt, lässt sich sonst nicht ausprobieren.
#   2. Die Plattform-CA entsteht auf dieser Maschine statt in der Zeremonie
#      auf dem Offline-Rechner (docs/runbooks/platform-ca.md). Form und
#      Wirkung sind dieselben: eine Wurzel, zwei Zwischenstellen, Client-
#      Zertifikate für Operatoren. Sie darf nichts ausserhalb dieses Hosts
#      bedeuten.
#
# Voraussetzungen: docker mit compose-Plugin, openssl, curl, python3 und
# age (für die Sicherungen). Node/pnpm braucht es NICHT: die Oberfläche der
# Konsole wird, wenn kein pnpm da ist, in einem Node-Container gebaut.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ZIEL="${PLATTFORM_ROOT:-$REPO/plattform}"
CERTS="$ZIEL/certs"
# Ablage der gebauten Agentenpakete; die Konsole liest sie nur (ADR-0014).
PAKETE="$ZIEL/agentenpakete"
NETZ="${PLATTFORM_NETZ:-magister-plattform}"

# --- Die drei Angaben, die eine Installation ausmachen -----------------------
#
# Sie werden bei der Erstinstallation EINMAL gefragt und stehen danach in
# `$KONF`. Jeder weitere Aufruf — `up`, `status`, `down`, `operator` — liest
# sie von dort.
#
# Der Fehler, den das behebt, hat zweimal denselben Abend gekostet: BIND und
# ZUSATZNAME waren blosse Optionen mit Vorgabewert. Ein `up` ohne Optionen
# lief deshalb mit `127.0.0.1` und „localhost" — und weil `write_env` die
# Adressen in eine bestehende `.env` nachführt, machte jedes Update die
# Installation wieder unerreichbar. Wer die Optionen beim ersten Mal richtig
# gesetzt hatte, verlor sie beim ersten `git pull && up`.
#
# Die Regel dagegen: **ein Update vergisst keine Antwort, die beim Aufbau
# gegeben wurde.** Ein Vorgabewert darf einen gespeicherten Wert nie
# überschreiben — nur eine ausdrückliche Angabe darf das.
#
# Rangfolge, von stark nach schwach:
#   1. Option auf der Kommandozeile (`--bind …`)  — wird gespeichert
#   2. Umgebungsvariable (`PLATTFORM_BIND=…`)     — wird gespeichert
#   3. gespeicherte Konfiguration ($KONF)
#   4. Rückfrage bei der Erstinstallation
#   5. Vorgabe (nur, wenn niemand fragen kann — CI, Cron)
KONF="${PLATTFORM_KONF:-$ZIEL/plattform.conf}"

VORGABE_DOMAIN="dev-mgmt.int.vitabrevis.ch"
VORGABE_BIND="127.0.0.1"

# Leer heisst hier „noch unbeantwortet". Die `_GESETZT`-Flaggen unterscheiden
# das von einer ausdrücklichen leeren Antwort — ZUSATZNAME darf leer sein.
DOMAIN="${PLATTFORM_DOMAIN:-}"
BIND="${PLATTFORM_BIND:-}"
ZUSATZNAME="${PLATTFORM_ZUSATZNAME:-}"
DOMAIN_GESETZT=0; [ -n "${PLATTFORM_DOMAIN:-}" ] && DOMAIN_GESETZT=1
BIND_GESETZT=0;   [ -n "${PLATTFORM_BIND:-}" ]   && BIND_GESETZT=1
ZUSATZNAME_GESETZT=0
[ -n "${PLATTFORM_ZUSATZNAME+x}" ] && ZUSATZNAME_GESETZT=1
KONSOLE_HOST=""
KUNDEN=("thun" "bern")
ZIEHEN=0
# `--ui-neu` baut die Oberfläche auch dann, wenn sie aktuell aussieht — für
# den Fall, dass die Erkennung über die Zeitstempel danebenliegt.
UI_NEU=0
# `purge --auch-konfiguration` löscht auch die Angaben zur Installation.
KONF_LOESCHEN=0

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m !  %s\033[0m\n' "$*"; }
die()  { printf '\033[31m !! %s\033[0m\n' "$*" >&2; exit 1; }

dc_konsole() {
  docker compose --project-directory "$REPO/cockpit/deploy" \
    -f "$REPO/cockpit/deploy/docker-compose.yml" \
    -f "$REPO/cockpit/deploy/docker-compose.plattform.yml" "$@"
}

dc_daten() {
  local bauen=()
  [ "$ZIEHEN" -eq 0 ] && bauen=(-f "$REPO/deploy/compose/docker-compose.build.yml")
  docker compose --project-directory "$REPO/deploy/compose" \
    -f "$REPO/deploy/compose/docker-compose.yml" \
    -f "$REPO/deploy/compose/docker-compose.plattform.yml" \
    "${bauen[@]}" "$@"
}

secret() { openssl rand -hex 32; }

setze_wert() {  # $1 = Datei, $2 = Schlüssel, $3 = Wert -> 0 wenn geändert
  local datei="$1" schluessel="$2" wert="$3" alt
  alt="$(grep -oP "(?<=^$schluessel=).*" "$datei" 2>/dev/null || true)"
  [ "$alt" = "$wert" ] && return 1
  if [ -n "$alt" ]; then
    sed -i "s|^$schluessel=.*|$schluessel=$wert|" "$datei"
  else
    echo "$schluessel=$wert" >> "$datei"
  fi
  return 0
}

# --- Konfiguration der Installation ------------------------------------------
konf_laden() {
  [ -f "$KONF" ] || return 0
  local schluessel wert
  # Nur bekannte Schlüssel, und `read` statt `source`: die Datei wird nicht
  # ausgeführt. Sie liegt neben Zertifikaten und Kundendaten — ein Skript,
  # das sie ausführt, macht aus einem Schreibrecht ein Ausführungsrecht.
  #
  # Ein gelesener Schlüssel gilt danach als beantwortet — auch ein leerer.
  # Sonst fragte die Erstinstallation nach dem zweiten Namen erneut, wenn
  # man ihn beim ersten Mal weggelassen hat: leer wäre dann nicht „keiner",
  # sondern „noch nicht gesagt", und die Frage käme bei jedem Update wieder.
  while IFS='=' read -r schluessel wert; do
    case "$schluessel" in
      PLATTFORM_DOMAIN)
        if [ "$DOMAIN_GESETZT" -eq 0 ]; then DOMAIN="$wert"; DOMAIN_GESETZT=1; fi ;;
      PLATTFORM_BIND)
        if [ "$BIND_GESETZT" -eq 0 ]; then BIND="$wert"; BIND_GESETZT=1; fi ;;
      PLATTFORM_ZUSATZNAME)
        if [ "$ZUSATZNAME_GESETZT" -eq 0 ]; then ZUSATZNAME="$wert"; ZUSATZNAME_GESETZT=1; fi ;;
    esac
  done < <(grep -E '^PLATTFORM_[A-Z_]+=' "$KONF" || true)
}

#: Vorschlag für die Adresse dieser Maschine — die, über die sie ins Netz
#: schaut. Nicht geraten, sondern aus der Routing-Tabelle.
vorschlag_ip() {
  ip route get 1.1.1.1 2>/dev/null | grep -oP '(?<=src )\S+' | head -1 || true
}

vorschlag_fqdn() {
  hostname -f 2>/dev/null || hostname 2>/dev/null || true
}

frage() {  # $1 = Text, $2 = Vorschlag -> Antwort auf stdout
  local antwort=""
  printf '\033[1m ?  %s\033[0m [%s]: ' "$1" "$2" > /dev/tty
  read -r antwort < /dev/tty || true
  printf '%s' "${antwort:-$2}"
}

konf_erfragen() {  # nur bei `up`, nur was fehlt, nur mit Terminal
  # PLATTFORM_NICHT_FRAGEN: für CI und für scripts/tests — dann gelten die
  # Vorgaben, statt dass ein Lauf ohne Bediener an einer Frage hängt.
  if [ -n "${PLATTFORM_NICHT_FRAGEN:-}" ]; then return 0; fi
  if [ ! -r /dev/tty ] || [ ! -w /dev/tty ]; then return 0; fi
  if [ "$DOMAIN_GESETZT" -eq 1 ] && [ "$BIND_GESETZT" -eq 1 ] \
     && [ "$ZUSATZNAME_GESETZT" -eq 1 ]; then
    return 0
  fi
  if [ ! -f "$KONF" ]; then
    cat > /dev/tty <<'HINWEIS'

Erstinstallation. Drei Angaben, danach stehen sie in der Konfiguration und
werden nie wieder gefragt — auch nicht bei einem Update.

HINWEIS
  fi
  if [ "$DOMAIN_GESETZT" -eq 0 ]; then
    DOMAIN="$(frage 'Domäne, unter der die Kundennamen liegen' "$VORGABE_DOMAIN")"
  fi
  if [ "$BIND_GESETZT" -eq 0 ]; then
    local vorschlag
    vorschlag="$(vorschlag_ip)"
    printf '    Die Konsole lauscht nur auf dieser Adresse. NICHT 0.0.0.0.\n' > /dev/tty
    BIND="$(frage 'Verwaltungsadresse der Konsole' "${vorschlag:-$VORGABE_BIND}")"
  fi
  if [ "$ZUSATZNAME_GESETZT" -eq 0 ]; then
    printf '    Zweiter Name derselben Konsole (FQDN dieser Maschine). Er kommt\n' > /dev/tty
    printf '    in das Zertifikat UND in den Site-Block von Caddy — fehlt er,\n' > /dev/tty
    printf '    endet ein Aufruf unter diesem Namen in 421.\n' > /dev/tty
    ZUSATZNAME="$(frage 'Zweiter Name (leer = keiner)' "$(vorschlag_fqdn)")"
  fi
  DOMAIN_GESETZT=1; BIND_GESETZT=1; ZUSATZNAME_GESETZT=1
  printf '\n' > /dev/tty
}

konf_anwenden() {
  # Vorgaben NUR für das, was niemand beantwortet hat.
  DOMAIN="${DOMAIN:-$VORGABE_DOMAIN}"
  BIND="${BIND:-$VORGABE_BIND}"
  KONSOLE_HOST="konsole.$DOMAIN"
  [ "$BIND" = "0.0.0.0" ] && die "0.0.0.0 ist nicht zulässig: die Konsole gehört auf eine Verwaltungsadresse (ADR-0015 D1)."
  return 0
}

konf_speichern() {
  mkdir -p "$(dirname "$KONF")"
  cat > "$KONF" <<EOF
# Die Angaben zu DIESER Installation. Erzeugt von plattform-aufbau.sh,
# gelesen von jedem weiteren Aufruf. Von Hand änderbar; ein `up` mit
# --domaene/--bind/--zusatzname schreibt die neuen Werte hierher zurück.
#
# Diese Datei überlebt ein `purge` (sie enthält keine Geheimnisse und keine
# Kundendaten). Wirklich alles weg: purge --auch-konfiguration
PLATTFORM_DOMAIN=$DOMAIN
PLATTFORM_BIND=$BIND
PLATTFORM_ZUSATZNAME=$ZUSATZNAME
EOF
}

# --- Voraussetzungen ---------------------------------------------------------
preflight() {
  for werkzeug in docker openssl curl python3; do
    command -v "$werkzeug" >/dev/null || die "$werkzeug fehlt."
  done
  docker compose version >/dev/null 2>&1 || die "Das compose-Plugin von Docker fehlt (docker-compose-plugin)."
  docker info >/dev/null 2>&1 || die "Der Docker-Dienst antwortet nicht (systemctl start docker)."
  command -v age >/dev/null || warn "age fehlt — Sicherungen lassen sich nicht prüfen."
  # Kein Hinweis mehr auf fehlendes pnpm: gibt es keines, baut `build_ui`
  # die Oberfläche in einem Node-Container. Auf einem Server, der Container
  # fährt, ist das der passendere Weg — und eine Voraussetzung weniger.
  # 443 und 80 gehören dem Kunden-Listener. Belegt heisst: ein anderer
  # Webserver steht im Weg, und Caddy bekäme den Port nicht.
  for port in 80 443 4444; do
    local ziel="127.0.0.1"
    [ "$port" = "4444" ] && ziel="$BIND"
    if (exec 3<>"/dev/tcp/$ziel/$port") 2>/dev/null; then
      exec 3<&- 3>&-
      warn "Port $port ist belegt — wenn das nicht dieser Stack ist, scheitert Caddy beim Start."
    fi
  done
}

# --- Plattform-CA ------------------------------------------------------------
# Dieselbe Form wie in der Zeremonie: Wurzel, zwei Zwischenstellen, daraus
# Server- und Client-Zertifikate. Was hier entsteht, ist eine TEST-CA.
make_ca() {
  mkdir -p "$CERTS"
  if [ -f "$CERTS/root.pem" ]; then
    # Nachtragen, was eine frühere Fassung dieses Skripts noch nicht schrieb:
    # der Trust Pool für Client-Zertifikate ist eine eigene Datei geworden.
    [ -f "$CERTS/operator-ca.pem" ] || cp "$CERTS/operator-int.pem" "$CERTS/operator-ca.pem"
    # Und prüfen, ob das Konsolenzertifikat die verlangten Namen überhaupt
    # trägt. Ein Name, der fehlt, lässt sich nicht nachtragen — nur das
    # Zertifikat neu ausstellen. Genau das blieb bisher aus, und der Aufruf
    # unter dem neuen Namen scheiterte an einem Zertifikat, das ihn nicht
    # kennt.
    if ! zertifikat_deckt_ab; then
      say "Konsolenzertifikat neu ausstellen (Adressen haben sich geändert)"
      konsolen_zertifikat
    else
      say "Plattform-CA steht bereits"
    fi
    return
  fi
  say "Plattform-CA erzeugen (Test-CA für $DOMAIN)"
  openssl req -x509 -newkey rsa:3072 -sha256 -days 825 -nodes \
    -keyout "$CERTS/root-key.pem" -out "$CERTS/root.pem" \
    -subj "/CN=Magister Plattform Root ($DOMAIN)" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null

  for zweck in operator connector; do
    openssl req -newkey rsa:3072 -nodes -keyout "$CERTS/$zweck-int-key.pem" \
      -out "$CERTS/$zweck-int.csr" -subj "/CN=Magister $zweck Intermediate" 2>/dev/null
    openssl x509 -req -in "$CERTS/$zweck-int.csr" -CA "$CERTS/root.pem" \
      -CAkey "$CERTS/root-key.pem" -CAcreateserial -days 730 -sha256 \
      -out "$CERTS/$zweck-int.pem" \
      -extfile <(printf 'basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\n') 2>/dev/null
  done
  # ZWEI Dateien, weil es zwei Fragen sind, und eine Datei für beide die
  # schwächere Antwort gibt:
  #
  #   platform-ca.pem  — „ist dieser SERVER echt?" Wurzel plus Operator-Zweig;
  #                      damit prüfen Browser und curl das Zertifikat der
  #                      Konsole.
  #   operator-ca.pem  — „darf dieser CLIENT überhaupt anklopfen?" NUR der
  #                      Operator-Zweig. Läge die Wurzel darin, genügte dem
  #                      Listener jedes Zertifikat unter ihr — auch das eines
  #                      Connector-Agenten, und davon hat jeder Kunde eines im
  #                      eigenen Netz. Nachgemessen mit `openssl verify`: mit
  #                      Wurzel im Pool geht ein Agentenzertifikat durch, mit
  #                      nur dem Operator-Zweig nicht. Die Anwendung wiese es
  #                      danach ab (unbekanntes Zertifikat, keine Sitzung) —
  #                      aber die zweite von drei Schichten hätte nicht
  #                      gehalten.
  cat "$CERTS/root.pem" "$CERTS/operator-int.pem" > "$CERTS/platform-ca.pem"
  cp "$CERTS/operator-int.pem" "$CERTS/operator-ca.pem"

  # Serverzertifikat der Konsole — mit allen Adressen, unter denen sie
  # gerufen wird.
  konsolen_zertifikat
  # Serverzertifikat für ALLE Kundennamen. Der Platzhalter gilt für genau
  # eine Ebene — deshalb steht die Kundenebene hier ausdrücklich.
  zertifikat "tenants" "*.$DOMAIN" "DNS:*.$DOMAIN,DNS:$DOMAIN"
  # Der Connector-Listener auf 46200 (ADR-0014).
  zertifikat "connector" "connect.$DOMAIN" "DNS:connect.$DOMAIN"

  # Client-Zertifikate: eine Person und die Überwachung, beide aus dem
  # Operator-Zweig.
  for wer in operator monitor; do
    openssl req -newkey rsa:3072 -nodes -keyout "$CERTS/$wer-key.pem" \
      -out "$CERTS/$wer.csr" -subj "/CN=$wer@$DOMAIN" 2>/dev/null
    openssl x509 -req -in "$CERTS/$wer.csr" -CA "$CERTS/operator-int.pem" \
      -CAkey "$CERTS/operator-int-key.pem" -CAcreateserial -days 365 -sha256 \
      -out "$CERTS/$wer.pem" \
      -extfile <(printf 'extendedKeyUsage=clientAuth\nkeyUsage=critical,digitalSignature\n') 2>/dev/null
  done

  # Der Signierschlüssel für Operator-Einlösescheine (ADR-0019).
  openssl genpkey -algorithm ed25519 -out "$CERTS/operator-signing.pem" 2>/dev/null

  # Empfänger für die verschlüsselten Sicherungen (ADR-0016 D9). In
  # Produktion entsteht der private Teil auf dem Sicherungs-Host und bleibt
  # dort; hier liegt er daneben, damit `backup verify` überhaupt prüfbar ist.
  if command -v age-keygen >/dev/null; then
    age-keygen -o "$CERTS/backup-age.key" 2>/dev/null
    grep "public key:" "$CERTS/backup-age.key" | awk '{print $NF}' > "$CERTS/backup-age.pub"
  fi
  chmod 600 "$CERTS"/*-key.pem "$CERTS/operator-signing.pem" 2>/dev/null || true
}

konsolen_san() {
  local san="DNS:$KONSOLE_HOST,DNS:localhost,IP:127.0.0.1"
  [ "$BIND" != "127.0.0.1" ] && san="$san,IP:$BIND"
  if [ -n "$ZUSATZNAME" ]; then
    # IP oder Name? Das sind verschiedene SAN-Typen, und ein Name im IP-Feld
    # macht das Zertifikat still unbrauchbar.
    if printf '%s' "$ZUSATZNAME" | grep -qE '^[0-9]+(\.[0-9]+){3}$'; then
      san="$san,IP:$ZUSATZNAME"
    else
      san="$san,DNS:$ZUSATZNAME"
    fi
  fi
  echo "$san"
}

konsolen_zertifikat() {
  zertifikat "console" "$KONSOLE_HOST" "$(konsolen_san)"
  cp -f "$CERTS/console.pem" "$CERTS/console-key.pem" "$REPO/cockpit/deploy/certs/" 2>/dev/null || true
}

zertifikat_deckt_ab() {  # Trägt das Konsolenzertifikat alle verlangten Namen?
  [ -f "$CERTS/console.pem" ] || return 1
  local vorhanden fehlt=0
  vorhanden="$(openssl x509 -in "$CERTS/console.pem" -noout -ext subjectAltName 2>/dev/null)"
  local eintrag
  for eintrag in $(konsolen_san | tr ',' ' '); do
    case "$eintrag" in
      DNS:*) echo "$vorhanden" | grep -q "DNS:${eintrag#DNS:}\b" || fehlt=1 ;;
      IP:*)  echo "$vorhanden" | grep -q "IP Address:${eintrag#IP:}\b" || fehlt=1 ;;
    esac
  done
  [ "$fehlt" -eq 0 ]
}

zertifikat() {  # $1 = Name, $2 = CN, $3 = SAN
  openssl req -newkey rsa:3072 -nodes -keyout "$CERTS/$1-key.pem" \
    -out "$CERTS/$1.csr" -subj "/CN=$2" 2>/dev/null
  openssl x509 -req -in "$CERTS/$1.csr" -CA "$CERTS/root.pem" \
    -CAkey "$CERTS/root-key.pem" -CAcreateserial -days 730 -sha256 \
    -out "$CERTS/$1.pem" \
    -extfile <(printf 'subjectAltName=%s\nextendedKeyUsage=serverAuth\n' "$3") 2>/dev/null
}

# --- Umgebung ----------------------------------------------------------------
# Die beiden `.env`-Dateien sind dieselben wie in Produktion — nur die Werte
# entstehen hier per Zufall statt aus dem Passwortspeicher.
write_env() {
  mkdir -p "$ZIEL" "$PAKETE"
  local konsole_env="$REPO/cockpit/deploy/.env" daten_env="$REPO/deploy/compose/.env"

  if [ ! -f "$konsole_env" ]; then
    say "Umgebung der Konsole schreiben ($konsole_env)"
    cat > "$konsole_env" <<EOF
# --- erzeugt von plattform-aufbau.sh ---
COCKPIT_BIND_ADDRESS=$BIND
COCKPIT_HOSTNAME=$KONSOLE_HOST
COCKPIT_CONNECTOR_HOSTNAME=connect.$DOMAIN
# Die zweite Adresse desselben Listeners (IP oder FQDN der Maschine).
# Leer heisst 'localhost' — dann ist die Konsole nur über ihren Namen
# erreichbar, und ein Aufruf per IP endet in 421.
COCKPIT_EXTRA_HOST=${ZUSATZNAME:-$( [ "$BIND" != "127.0.0.1" ] && echo "$BIND" || echo "localhost" )}
COCKPIT_BOOTSTRAP_TOKEN=$(secret)
COCKPIT_SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n')
# Zwei Marker, zwingend verschieden: sonst öffnete jeder von beiden jeden
# Listener, und die Konsole verweigert den Start (ADR-0015 D1).
COCKPIT_MANAGEMENT_MARKER=$(secret)
COCKPIT_CONNECTOR_MARKER=$(secret)
# Verwaltungszugang in den Magister-Cluster. 'magister-db' ist der Name, den
# die Datenebene ihrer Postgres-Instanz im gemeinsamen Netz gibt — NICHT
# 'postgres': so heisst auch die Datenbank der Konsole selbst, und unter dem
# Namen legte sie die Kundenschemas bei sich an.
COCKPIT_TENANT_ADMIN_DSN=postgresql+asyncpg://magister:$(secret)@magister-db:5432/magister
COCKPIT_TENANT_EXTENSION_SCHEMA=public
COCKPIT_EXPECTED_SCHEMA_VERSION=$(grep -oE '"[0-9]{4}_[a-z_]+"' "$REPO/apps/api/magister_api/tenancy/version.py" | head -1 | tr -d '"')
COCKPIT_BACKUP_SHARE_ROOT=/var/backups/magister
COCKPIT_EXPORT_ROOT=/var/lib/magister/exports
COCKPIT_BACKUP_AGE_RECIPIENT=$( [ -f "$CERTS/backup-age.pub" ] && cat "$CERTS/backup-age.pub" || echo "" )
# Verzeichnis mit den gebauten Agentenpaketen (ADR-0014). Es wird unter
# demselben Pfad schreibgeschützt in die Konsole eingehängt; wer ein neues
# Paket ausliefern will, legt es hier ab. Leer bleibt es, bis die CI etwas
# hineinlegt — die Oberfläche sagt dann „nicht eingerichtet".
COCKPIT_AGENT_PACKAGE_DIR=$PAKETE
PLATTFORM_NETZ=$NETZ
EOF
    chmod 600 "$konsole_env"
  else
    # Bestehende Umgebung: Geheimnisse bleiben, Adressen werden nachgeführt.
    #
    # Der Fehler, den das hier behebt, kostete drei Anläufe: `up --bind …
    # --zusatzname …` auf eine vorhandene `.env` liess beide Optionen
    # stillschweigend fallen. Das Skript sagte „besteht bereits", der Kunde
    # las „alles gut", und der Listener hing weiter auf 127.0.0.1. Eine
    # Option, die nichts tut, ist schlimmer als eine, die es nicht gibt.
    local gewuenscht_extra
    gewuenscht_extra="${ZUSATZNAME:-$( [ "$BIND" != "127.0.0.1" ] && echo "$BIND" || echo "localhost" )}"
    # Alle drei prüfen, dann entscheiden. Mit `a || b || c` hört die Kette
    # nach der ersten Änderung auf — die Bindung wurde nachgeführt, der
    # zweite Name nicht, und der Aufruf scheiterte weiter. Beim ersten Test
    # dieses Fixes genau so passiert.
    local geaendert=0
    setze_wert "$konsole_env" COCKPIT_BIND_ADDRESS "$BIND" && geaendert=1
    setze_wert "$konsole_env" COCKPIT_EXTRA_HOST "$gewuenscht_extra" && geaendert=1
    setze_wert "$konsole_env" COCKPIT_HOSTNAME "$KONSOLE_HOST" && geaendert=1
    # Nachgereicht für Installationen, die vor den Agentenpaketen entstanden
    # sind: ohne den Wert hängt Compose den Vorgabepfad ein, und der liegt
    # bei einem eigenen PLATTFORM_ROOT woanders.
    setze_wert "$konsole_env" COCKPIT_AGENT_PACKAGE_DIR "$PAKETE" && geaendert=1
    if [ "$geaendert" -eq 1 ]; then
      say "Umgebung der Konsole nachgeführt (Adressen geändert)"
    else
      say "Umgebung der Konsole besteht bereits"
    fi
  fi

  # Das Passwort der Cluster-Rolle steht in BEIDEN Dateien und muss dasselbe
  # sein: die Konsole meldet sich damit an, die Datenebene legt die Rolle an.
  local pg_pw
  pg_pw="$(grep -oP '(?<=://magister:)[^@]+' "$konsole_env")"

  if [ ! -f "$daten_env" ]; then
    say "Umgebung der Datenebene schreiben ($daten_env)"
    local marker token
    marker="$(grep -oP '(?<=^COCKPIT_MANAGEMENT_MARKER=).*' "$konsole_env")"
    token="$(grep -oP '(?<=^COCKPIT_BOOTSTRAP_TOKEN=).*' "$konsole_env")"
    cat > "$daten_env" <<EOF
# --- erzeugt von plattform-aufbau.sh ---
POSTGRES_USER=magister
POSTGRES_PASSWORD=$pg_pw
POSTGRES_DB=magister
# Nur noch der Rückfall für Aufrufe ohne SNI; die Kundennamen stehen in der
# Registry der Konsole, nicht hier.
MAGISTER_PUBLIC_HOSTNAME=$KONSOLE_HOST
MAGISTER_TENANT_DOMAIN=$DOMAIN
MAGISTER_DEFAULT_SNI=$KONSOLE_HOST
MAGISTER_TENANT_CERT_DIR=$CERTS
MAGISTER_AUDIT_KEY=$(secret)
MAGISTER_SESSION_SECRET=$(secret)
MAGISTER_CSRF_SECRET=$(secret)
MAGISTER_HEALTH_TOKEN=$(secret)
MAGISTER_BACKUP_AGE_RECIPIENT=$( [ -f "$CERTS/backup-age.pub" ] && cat "$CERTS/backup-age.pub" || echo "" )
# Der Weg zur Konsole: über den Verwaltungs-Listener, mit beiden Nachweisen.
MAGISTER_CONSOLE_REGISTRY_URL=https://$KONSOLE_HOST:4444/api/tenants/registry
MAGISTER_CONSOLE_REGISTRY_TOKEN=$token
MAGISTER_CONSOLE_MANAGEMENT_MARKER=$marker
MAGISTER_CONSOLE_REGISTRY_INTERVAL_S=30
# OIDC: je Kunde eine eigene Einbindung (Entscheid aus der Prod-Planung).
# Hier leer — im Dev meldet man sich lokal an.
MAGISTER_OIDC_ISSUER=
MAGISTER_OIDC_CLIENT_ID=
MAGISTER_OIDC_CLIENT_SECRET=
PLATTFORM_NETZ=$NETZ
EOF
    chmod 600 "$daten_env"
  else
    # Dieselbe Nachführung wie oben, und aus demselben Grund: ändert sich
    # die Domäne, muss die Datenebene mitkommen. Sonst bedient Caddy
    # weiter die alten Kundennamen, während die Konsole die neuen kennt —
    # und niemand sieht, warum die Seite 421 sagt. Geheimnisse und
    # OIDC-Werte bleiben unangetastet.
    local geaendert=0
    setze_wert "$daten_env" MAGISTER_PUBLIC_HOSTNAME "$KONSOLE_HOST" && geaendert=1
    setze_wert "$daten_env" MAGISTER_TENANT_DOMAIN "$DOMAIN" && geaendert=1
    setze_wert "$daten_env" MAGISTER_DEFAULT_SNI "$KONSOLE_HOST" && geaendert=1
    setze_wert "$daten_env" MAGISTER_TENANT_CERT_DIR "$CERTS" && geaendert=1
    setze_wert "$daten_env" MAGISTER_CONSOLE_REGISTRY_URL \
      "https://$KONSOLE_HOST:4444/api/tenants/registry" && geaendert=1
    if [ "$geaendert" -eq 1 ]; then
      say "Umgebung der Datenebene nachgeführt (Namen geändert)"
    else
      say "Umgebung der Datenebene besteht bereits"
    fi
  fi
}

# --- Oberflächen -------------------------------------------------------------
build_ui() {
  # Die gebaute Oberfläche ist keine Kür: Caddy hängt `cockpit/web/dist`
  # ein und liefert daraus alles aus, was nicht `/api/*` ist. Fehlt sie,
  # antwortet die Konsole im Browser mit **404** — die API läuft, die Seite
  # gibt es nicht. Genau so auf dev01 passiert.
  #
  # Und zwar die AKTUELLE. Die frühere Fassung dieser Zeilen stieg aus,
  # sobald `dist/index.html` überhaupt existierte — mit dem Satz
  # „Konsolen-Oberfläche steht bereits". Nach einem `git pull` mit einer
  # neuen Ansicht meldete `up` also Vollzug, und im Browser fehlte sie.
  # Dieselbe Falle wie beim Werkzeug im Container: ausgeliefert wird, was
  # beim letzten Bauen entstand, nicht was im Arbeitsbaum liegt.
  #
  # `find -newer` statt eines Zeitstempels im Skript: ein `git checkout`
  # setzt die mtime der geänderten Dateien auf jetzt, und genau danach wird
  # hier gefragt.
  if [ -f "$REPO/cockpit/web/dist/index.html" ] && [ "$UI_NEU" -eq 0 ]; then
    local neuer=""
    for quelle in src package.json pnpm-lock.yaml index.html vite.config.ts \
                  tailwind.config.js postcss.config.js tsconfig.json; do
      [ -e "$REPO/cockpit/web/$quelle" ] || continue
      neuer="$(find "$REPO/cockpit/web/$quelle" \
                 -newer "$REPO/cockpit/web/dist/index.html" -print -quit 2>/dev/null)"
      # Kein `[ -n … ] && break`: schlägt der Test in der letzten Runde fehl,
      # endet die Schleife mit Status 1 und `set -e` bricht das Skript ab.
      if [ -n "$neuer" ]; then break; fi
    done
    if [ -z "$neuer" ]; then
      say "Konsolen-Oberfläche steht bereits und ist aktuell ($REPO/cockpit/web/dist)"
      return 0
    fi
    say "Quellstand ist neuer als der Bau (${neuer#"$REPO"/cockpit/web/}) — neu bauen"
  fi

  if command -v pnpm >/dev/null; then
    say "Konsolen-Oberfläche bauen"
    (cd "$REPO/cockpit/web" && pnpm install --silent && pnpm build >/dev/null)
    return 0
  fi

  # Kein pnpm auf dem Host — und das soll auch nicht nötig sein. Node
  # gehört nicht auf einen Server, der Container fährt; die Werkzeugkette
  # kommt aus einem Abbild und verschwindet danach wieder. Derselbe
  # Gedanke wie bei allem anderen hier.
  say "Konsolen-Oberfläche im Container bauen (kein pnpm auf dem Host)"
  local protokoll="$ZIEL/ui-bau.log"
  mkdir -p "$ZIEL"
  # Zwei Eigenheiten, beide teuer bezahlt:
  #
  # COREPACK_ENABLE_DOWNLOAD_PROMPT=0 — Corepack lädt pnpm in der im Projekt
  # festgelegten Fassung nach und FRAGT vorher. An einem Terminal eine
  # Rückfrage, in einem Skript ohne TTY ein Abbruch. Von Hand lief derselbe
  # Befehl deshalb durch und im Skript nicht.
  #
  # --ignore-workspace — neuere pnpm-Fassungen legen eine
  # `pnpm-workspace.yaml` an, um Einstellungen abzulegen. Enthält die kein
  # `packages:`, bricht pnpm 10 beim nächsten Lauf ab: „packages field
  # missing or empty". Ein einziger Fehlversuch mit einer neueren Fassung
  # hinterlässt also eine Datei, die jeden folgenden Lauf verhindert. Hier
  # gibt es keinen Workspace, also geht die Datei uns nichts an.
  if ! docker run --rm -e COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
       -v "$REPO/cockpit/web:/arbeit" -w /arbeit node:22-alpine \
       sh -c 'corepack enable pnpm && pnpm install --ignore-workspace && pnpm build' \
       > "$protokoll" 2>&1; then
    warn "Der Bau der Oberfläche ist gescheitert. Die Konsole antwortet dann nur auf /api/*."
    # Die Ausgabe zeigen und nicht verstecken. Ein Skript, das den Grund
    # wegwirft, macht aus einem benennbaren Fehler eine Suche.
    printf '\033[33m    Letzte Zeilen aus %s:\033[0m\n' "$protokoll" >&2
    tail -15 "$protokoll" >&2
    return 0
  fi
  [ -f "$REPO/cockpit/web/dist/index.html" ] \
    || warn "Der Bau lief durch, aber dist/index.html fehlt — bitte die Ausgabe von Hand ansehen."
}

# --- Stacks ------------------------------------------------------------------
netz() {
  docker network inspect "$NETZ" >/dev/null 2>&1 && return 0
  say "Gemeinsames Netz anlegen ($NETZ)"
  docker network create "$NETZ" >/dev/null
}

start_konsole() {
  # Die Zertifikate liegen dort, wo die Compose-Datei sie erwartet.
  mkdir -p "$REPO/cockpit/deploy/certs"
  for datei in platform-ca.pem operator-ca.pem console.pem console-key.pem \
               connector.pem connector-key.pem \
               connector-int.pem connector-int-key.pem operator-signing.pem; do
    cp -f "$CERTS/$datei" "$REPO/cockpit/deploy/certs/$datei"
  done
  say "Konsole starten (Container, Listener auf $BIND:4444)"
  # `--build`, weil das Abbild der Konsole aus dem Arbeitsstand entsteht:
  # ohne das startet `up` das Abbild von gestern weiter, und eine Korrektur
  # am Code wirkt erst nach einem Handgriff, den niemand dokumentiert hat.
  dc_konsole up -d --build
  # Caddy IMMER neu erzeugen, nicht nur bei geänderten Adressen.
  #
  # Compose erkennt Änderungen an Abbild, Umgebung und Mounts — aber nicht
  # am INHALT einer eingehängten Datei. Die Caddy-Konfiguration ist genau so
  # eine Datei, und sie ändert sich öfter als alles andere hier. Gemessen:
  # nach einem `git pull`, der das Client-Zertifikat optional machte, lief
  # Caddy weiter mit der alten Regel und wies den Browser ab
  # (ERR_BAD_SSL_CLIENT_AUTH_CERT) — während die Datei auf der Platte schon
  # das Richtige sagte. Ein Neustart kostet eine Sekunde.
  say "Caddy neu starten (die Konfiguration ist eine eingehängte Datei)"
  dc_konsole up -d --force-recreate caddy
  dc_konsole exec -T api alembic upgrade head >/dev/null
  warte "Konsole" "https://$KONSOLE_HOST:4444/api/health" --cert
}

start_daten() {
  say "Datenebene starten (Container, Kundenseiten auf 443)"
  if [ "$ZIEHEN" -eq 1 ]; then dc_daten pull --quiet; else dc_daten build --quiet; fi
  dc_daten up -d
}

warte() {  # $1 = Name, $2 = URL, $3 = --cert wenn Client-Zertifikat nötig
  # Auf $BIND und nicht auf 127.0.0.1: mit `--bind 10.x.y.z` ist der Port
  # genau dort veröffentlicht und sonst nirgends. Die feste Loopback-Zeile
  # war der Grund, warum `up` „Konsole antwortet nicht" meldete, während
  # die Konsole im Log fröhlich `GET /api/health 200 OK` schrieb.
  local i=0 args=(-sS -o /dev/null --noproxy '*' -k
                  --resolve "$KONSOLE_HOST:4444:$BIND")
  [ "${3:-}" = "--cert" ] && args+=(--cert "$CERTS/operator.pem" --key "$CERTS/operator-key.pem")
  while [ "$i" -lt 60 ]; do
    curl "${args[@]}" "$2" 2>/dev/null && { say "$1 antwortet"; return 0; }
    sleep 2; i=$((i+1))
  done
  # Den Grund gleich mitliefern statt auf das Log zu verweisen: das Skript
  # hat es vor sich, der Bediener müsste erst einen zweiten Befehl mit drei
  # Pfaden tippen.
  printf '\033[31m !! %s antwortet nicht. Letzte Zeilen der Container:\033[0m\n' "$1" >&2
  dc_konsole logs --tail 20 api caddy 2>&1 | tail -30 >&2
  exit 1
}

# --- Kunden ------------------------------------------------------------------
# Über die API der Konsole, durch den Verwaltungs-Listener, mit Client-
# Zertifikat und Marker — also genau auf dem Weg, den auch ein Operator geht.
# Die Antwort enthält die Geheimnisse des Kunden; sie gehen in die `.env` der
# Datenebene, nicht in die Konsole (ADR-0013 D4).
konsole_api() {  # $1 = Methode, $2 = Pfad, $3 = Rumpf
  local token args
  token="$(grep -oP '(?<=^COCKPIT_BOOTSTRAP_TOKEN=).*' "$REPO/cockpit/deploy/.env")"
  args=(-sS --noproxy '*' -k -o /dev/stdout -w "\n%{http_code}"
        --resolve "$KONSOLE_HOST:4444:$BIND"
        --cert "$CERTS/operator.pem" --key "$CERTS/operator-key.pem"
        -X "$1" "https://$KONSOLE_HOST:4444$2"
        -H "Authorization: Bearer $token")
  [ $# -ge 3 ] && args+=(-H "Content-Type: application/json" -d "$3")
  curl "${args[@]}" 2>/dev/null
}

make_kunden() {
  local daten_env="$REPO/deploy/compose/.env" liste antwort id
  liste="$(konsole_api GET "/api/tenants")"
  for slug in "${KUNDEN[@]}"; do
    id="$(echo "$liste" | python3 -c '
import json, sys
zeilen = sys.stdin.read().rsplit("\n", 1)[0]
for t in json.loads(zeilen or "[]"):
    if t["slug"] == sys.argv[1]:
        print(t["id"] if not t.get("schema_version") else "fertig")
' "$slug" 2>/dev/null)"
    if [ "$id" = "fertig" ]; then
      say "Kunde $slug besteht bereits"
      continue
    elif [ -n "$id" ]; then
      say "Kunde $slug ist halb bereitgestellt — Auftrag fortsetzen"
      antwort="$(konsole_api POST "/api/tenants/$id/provisioning/resume")"
    else
      say "Kunde $slug bereitstellen"
      antwort="$(konsole_api POST "/api/tenants" \
        "{\"slug\":\"$slug\",\"name\":\"${slug^} (Plattform)\",\"hostname\":\"$slug.$DOMAIN\"}")"
    fi
    if ! python3 - "$antwort" "$daten_env" <<'PY'
import json, re, sys, pathlib

rumpf, code = sys.argv[1].rsplit("\n", 1)
if code not in ("200", "201", "202"):
    print(f"  ! Die Konsole antwortete mit HTTP {code}: {rumpf[:160]}")
    sys.exit(3)
data = json.loads(rumpf)
tenant, job = data["tenant"], data["job"]
# ZWEI Bezeichner, und sie sind nicht dasselbe: der DSN hängt am `dsn_ref`,
# die drei Schlüssel am **Slug**. Wer hier Refs einsetzt, bekommt eine
# Datenebene, die beide Kunden mit Wartung bedient.
ref = tenant["dsn_ref"].upper()
slug_ref = tenant["slug"].upper().replace("-", "_")
neu = {}
if data.get("role_password"):
    neu[f"MAGISTER_TENANT_DSN_{ref}"] = (
        f"postgresql+asyncpg://{tenant['db_role']}:{data['role_password']}"
        f"@postgres:5432/magister"
    )
if data.get("data_key"):
    neu[f"MAGISTER_TENANT_AUDIT_KEY_{slug_ref}"] = data["data_key"]
    neu[f"MAGISTER_TENANT_AUDIT_KEY_ID_{slug_ref}"] = f"{tenant['slug']}-1"
    neu[f"MAGISTER_TENANT_SECRETS_KEY_{slug_ref}"] = data["data_key"]

env = pathlib.Path(sys.argv[2])
inhalt = env.read_text()
vorhanden = dict(re.findall(r"^(MAGISTER_TENANT_\w+)=(.*)$", inhalt, re.M))
namen = [
    f"MAGISTER_TENANT_DSN_{ref}",
    f"MAGISTER_TENANT_AUDIT_KEY_{slug_ref}",
    f"MAGISTER_TENANT_AUDIT_KEY_ID_{slug_ref}",
    f"MAGISTER_TENANT_SECRETS_KEY_{slug_ref}",
]
# Zusammenführen statt anhängen: ein fortgesetzter Auftrag bringt nur die
# Geheimnisse der Schritte mit, die er wirklich ausgeführt hat.
werte = {n: neu.get(n, vorhanden.get(n, "")) for n in namen}
inhalt = re.sub(rf"\n?# --- Kunde {tenant['slug']} ---\n", "\n", inhalt)
for n in namen:
    inhalt = re.sub(rf"^{n}=.*\n", "", inhalt, flags=re.M)
zeilen = [f"# --- Kunde {tenant['slug']} ---"]
zeilen += [f"{n}={werte[n]}" for n in namen if werte[n]]
env.write_text(inhalt.rstrip("\n") + "\n\n" + "\n".join(zeilen) + "\n")

print(f"  {tenant['slug']}: Schema {tenant['schema_name']}, Rolle {tenant['db_role']}, "
      f"Stand {tenant['schema_version'] or 'keiner'}")
gescheitert = [s for s in job["steps"] if not s["ok"]]
if gescheitert:
    print(f"\n  ! Bereitstellung von {tenant['slug']} hing bei "
          f"{gescheitert[0]['step']}: {gescheitert[0]['detail']}")
    sys.exit(3)
PY
    then
      die "Bereitstellung unvollständig. Ursache oben beheben, dann erneut 'up' — der Auftrag wird fortgesetzt."
    fi
  done
  # Die neuen Kundenwerte stehen jetzt in der `.env`; der Container hat sie
  # beim Start noch nicht gesehen.
  say "Datenebene mit den Kundenwerten neu starten"
  dc_daten up -d --force-recreate magister-api >/dev/null
}

# --- Befehle -----------------------------------------------------------------
cmd_up() {
  # Prüfhilfe: die Angaben festschreiben und aufhören. Damit lässt sich die
  # Rangfolge aus dem Kopf dieser Datei testen, ohne Docker und ohne eine
  # halbe Plattform (scripts/tests/plattform-konfig.test.sh).
  if [ -n "${PLATTFORM_NUR_KONFIG:-}" ]; then cmd_konfig; return 0; fi
  preflight
  make_ca
  write_env
  build_ui
  netz
  start_konsole
  start_daten
  make_kunden
  cmd_status
  cat <<EOF

$(printf '\033[1mNächste Schritte\033[0m')

  1. Namen auflösbar machen (einmalig, als root) — in Produktion macht das
     der DNS, hier reicht die Datei:
       echo "$BIND $KONSOLE_HOST ${KUNDEN[0]}.$DOMAIN ${KUNDEN[1]}.$DOMAIN" >> /etc/hosts

  2. Ersten Operator anlegen (Passwort wird abgefragt, ADR-0023 D5):
       docker compose --project-directory $REPO/cockpit/deploy \\
         -f $REPO/cockpit/deploy/docker-compose.yml \\
         -f $REPO/cockpit/deploy/docker-compose.plattform.yml \\
         exec api python -m cockpit_api.cli.add_operator \\
           --upn vorname.nachname@vitabrevis.ch --name "Vorname Nachname" --set-password

  3. Konsole öffnen: https://$KONSOLE_HOST:4444${ZUSATZNAME:+ (oder https://$ZUSATZNAME:4444)}
     Anmeldung mit Benutzername, Passwort und Code. Ein Client-Zertifikat
     ist möglich, aber nicht nötig (ADR-0023 D3) — wer eines benutzen will,
     nimmt $CERTS/operator.pem (+ -key.pem), als PKCS#12 für den Browser:
       openssl pkcs12 -export -inkey $CERTS/operator-key.pem \\
         -in $CERTS/operator.pem -certfile $CERTS/platform-ca.pem \\
         -out $CERTS/operator.p12 -passout pass:dev

  4. Kundenseite öffnen: https://${KUNDEN[0]}.$DOMAIN
     (Die Plattform-CA $CERTS/root.pem im Browser als vertrauenswürdig
     eintragen, sonst warnt er — in Produktion kommt sie über die GPO.)

  5. Prüfen: die drei Handgriffe in
     docs/runbooks/plattform-auf-einem-host.md §5
EOF
}

cmd_status() {
  say "Zustand"
  dc_konsole ps --format '  konsole  {{.Service}}  {{.Status}}' 2>/dev/null || true
  dc_daten ps --format '  daten    {{.Service}}  {{.Status}}' 2>/dev/null || true
  local token
  token="$(grep -oP '(?<=^MAGISTER_HEALTH_TOKEN=).*' "$REPO/deploy/compose/.env" 2>/dev/null || true)"
  for slug in "${KUNDEN[@]}"; do
    local antwort
    antwort="$(curl -sS -k --noproxy '*' --resolve "$slug.$DOMAIN:443:127.0.0.1" \
      -H "X-Magister-Health: $token" \
      "https://$slug.$DOMAIN/healthz/stack" 2>/dev/null || true)"
    if [ -z "$antwort" ]; then
      printf '  %-8s keine Antwort\n' "$slug"
    else
      python3 - "$antwort" "$slug" <<'PY'
import json, sys
try:
    daten = json.loads(sys.argv[1])
except ValueError:
    print(f"  {sys.argv[2]:<8} unlesbare Antwort"); raise SystemExit
stufe = {0: "Stufe 0 (ok)", 1: "Stufe 1 (warning)", 2: "Stufe 2 (critical)"}
schlimm = [c for c in daten.get("checks", []) if c["status"] > 0]
zusatz = f" — {schlimm[0]['name']}: {schlimm[0]['detail']}" if schlimm else ""
print(f"  {sys.argv[2]:<8} {stufe.get(daten.get('status'), '?')}{zusatz}")
PY
    fi
  done
}

cmd_down() {
  say "Beide Stacks anhalten"
  dc_daten down 2>/dev/null || true
  dc_konsole down 2>/dev/null || true
}

cmd_purge() {
  cmd_down
  say "Daten, Netze und Geheimnisse löschen"
  dc_daten down -v 2>/dev/null || true
  dc_konsole down -v 2>/dev/null || true
  docker network rm "$NETZ" >/dev/null 2>&1 || true
  rm -rf "$REPO/cockpit/deploy/certs" \
         "$REPO/cockpit/deploy/.env" "$REPO/deploy/compose/.env"
  # Alles unter $ZIEL — aber die Konfiguration bleibt, sofern sie dort liegt.
  # Sie enthält keine Geheimnisse und keine Kundendaten, nur die Antworten
  # aus der Erstinstallation. Wer sie mitlöscht, tippt sie beim
  # Wiederaufbau erneut — und tippt sie irgendwann anders.
  if [ "$KONF_LOESCHEN" -eq 1 ]; then
    rm -rf "$ZIEL" "$KONF"
    say "Gelöscht, samt Konfiguration — der nächste 'up' fragt wieder"
  else
    # `-name` und nicht `-path`: ein PLATTFORM_ROOT mit Schrägstrich am Ende
    # ergäbe einen Pfad, der nie gleich aussieht wie der, den find druckt.
    local behalten; behalten="$(basename "$KONF")"
    find "$ZIEL" -mindepth 1 -maxdepth 1 ! -name "$behalten" -exec rm -rf {} + 2>/dev/null || true
    say "Gelöscht — der nächste 'up' beginnt von vorn, mit denselben Angaben aus $KONF"
  fi
}

cmd_konfig() {
  # Im Format der Konfigurationsdatei: was hier steht, steht auch dort —
  # und lässt sich so ohne Umdeutung vergleichen. Die abgeleiteten Werte
  # darunter, damit niemand „konsole." vor die Domäne denken muss.
  if [ -f "$KONF" ]; then
    say "Angaben dieser Installation ($KONF)"
  else
    say "Angaben dieser Installation (noch nicht gespeichert, erst 'up' legt $KONF an)"
  fi
  printf 'PLATTFORM_DOMAIN=%s\n' "$DOMAIN"
  printf 'PLATTFORM_BIND=%s\n' "$BIND"
  printf 'PLATTFORM_ZUSATZNAME=%s\n' "$ZUSATZNAME"
  printf '# abgeleitet\n'
  printf 'KONSOLE_URL=https://%s:4444\n' "$KONSOLE_HOST"
  local namen=""
  for slug in "${KUNDEN[@]}"; do namen="$namen $slug.$DOMAIN"; done
  printf 'KUNDEN=%s\n' "${namen# }"
}

# --- Werkzeuge in der Konsole ------------------------------------------------
# `exec api python -m …` führt den Code aus, der beim BAUEN in das Abbild
# kopiert wurde. Ein `git pull` ändert daran nichts — das Werkzeug im
# Container ist dann älter als das Repository, und ein neues Argument
# existiert dort noch nicht („unrecognized arguments: --reset-mfa"). Genau
# so passiert.
#
# Diese zwei Befehle bauen das Abbild deshalb vorher neu und reichen alles
# Weitere unverändert durch:
#
#   ./scripts/plattform-aufbau.sh operator --upn … --name … --set-password
#   ./scripts/plattform-aufbau.sh operator --upn … --reset-mfa
#   ./scripts/plattform-aufbau.sh totp --upn … --code 123456
cmd_werkzeug() {  # $1 = Modul, Rest = Argumente
  local modul="$1"; shift
  say "Abbild der Konsole aktualisieren (damit das Werkzeug dem Repository entspricht)"
  dc_konsole up -d --build api >/dev/null
  dc_konsole exec api python -m "$modul" "$@"
}

BEFEHL="${1:-up}"; shift || true

# Die gespeicherten Angaben zuerst — auch für `status`, `down` und die
# Werkzeuge. Vorher probte `status` stur die Vorgabeadresse und meldete
# „antwortet nicht", während die Konsole auf der Verwaltungsadresse lief.
konf_laden

# `operator` und `totp` nehmen die Argumente ihres Werkzeugs, nicht die
# dieses Skripts — deshalb vor der Optionsschleife.
case "$BEFEHL" in
  operator) konf_anwenden; cmd_werkzeug cockpit_api.cli.add_operator "$@"; exit $? ;;
  totp)     konf_anwenden; cmd_werkzeug cockpit_api.cli.totp_probe "$@"; exit $? ;;
esac

while [ $# -gt 0 ]; do
  case "$1" in
    --ziehen)  ZIEHEN=1; shift ;;
    --ui-neu)  UI_NEU=1; shift ;;
    --domaene) DOMAIN="$2"; DOMAIN_GESETZT=1; shift 2 ;;
    --bind)    BIND="$2"; BIND_GESETZT=1; shift 2 ;;
    --zusatzname) ZUSATZNAME="$2"; ZUSATZNAME_GESETZT=1; shift 2 ;;
    --auch-konfiguration) KONF_LOESCHEN=1; shift ;;
    *) die "Unbekannte Option: $1" ;;
  esac
done

# Fragen darf nur `up`: ein `status` im Cron soll nicht auf eine Eingabe
# warten. Gespeichert wird ebenfalls nur bei `up` — ein `status --bind …`
# ist eine einmalige Auskunft und keine Entscheidung über die Installation.
case "$BEFEHL" in up|update) konf_erfragen ;; esac
konf_anwenden
case "$BEFEHL" in up|update) konf_speichern ;; esac

case "$BEFEHL" in
  up|update) cmd_up ;;
  status) cmd_status ;;
  down)   cmd_down ;;
  purge)  cmd_purge ;;
  konfig) cmd_konfig ;;
  *) die "Unbekannter Befehl: $BEFEHL (up/update, status, konfig, down, purge, operator, totp)" ;;
esac
