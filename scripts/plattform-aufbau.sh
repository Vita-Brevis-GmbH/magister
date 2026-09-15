#!/usr/bin/env bash
# Die gehostete Magister-Plattform auf EINEM Host — so, wie sie in
# Produktion steht.
#
#   ./scripts/plattform-aufbau.sh up      # aufbauen und starten
#   ./scripts/plattform-aufbau.sh status  # was läuft, was antwortet
#   ./scripts/plattform-aufbau.sh down    # beide Stacks anhalten
#   ./scripts/plattform-aufbau.sh purge   # anhalten UND alles löschen
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
# Voraussetzungen: docker mit compose-Plugin, openssl, curl, python3, pnpm
# (für die Konsolen-Oberfläche), age (für die Sicherungen).

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ZIEL="${PLATTFORM_ROOT:-$REPO/plattform}"
CERTS="$ZIEL/certs"
NETZ="${PLATTFORM_NETZ:-magister-plattform}"

# Die Ebene, unter der die Kundennamen liegen. In Produktion die echte
# Domäne, hier die interne Testdomäne.
DOMAIN="${PLATTFORM_DOMAIN:-dev-mgmt.int.vitabrevis.ch}"
KONSOLE_HOST="konsole.$DOMAIN"
# Die Adresse, auf der der Konsolen-Listener veröffentlicht wird. NIE
# 0.0.0.0 — die Konsole kann Sitzungen in jeden Kunden ausstellen.
BIND="${PLATTFORM_BIND:-127.0.0.1}"
# Zweite Adresse, unter der die Konsole gerufen wird: der FQDN oder die IP
# der Maschine. Sie kommt in das Zertifikat UND in den Site-Block von Caddy
# — ohne beides scheitert der Aufruf, einmal am Namen und einmal an 421.
ZUSATZNAME="${PLATTFORM_ZUSATZNAME:-}"
KUNDEN=("thun" "bern")
ZIEHEN=0

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

# --- Voraussetzungen ---------------------------------------------------------
preflight() {
  for werkzeug in docker openssl curl python3; do
    command -v "$werkzeug" >/dev/null || die "$werkzeug fehlt."
  done
  docker compose version >/dev/null 2>&1 || die "Das compose-Plugin von Docker fehlt (docker-compose-plugin)."
  docker info >/dev/null 2>&1 || die "Der Docker-Dienst antwortet nicht (systemctl start docker)."
  command -v age >/dev/null || warn "age fehlt — Sicherungen lassen sich nicht prüfen."
  command -v pnpm >/dev/null || warn "pnpm fehlt — die Konsolen-Oberfläche wird nicht gebaut; der Listener antwortet dann nur auf /api/*."
  [ "$BIND" = "0.0.0.0" ] && die "PLATTFORM_BIND=0.0.0.0 ist nicht zulässig: die Konsole gehört auf eine Verwaltungsadresse (ADR-0015 D1)."
  # 443 und 80 gehören dem Kunden-Listener. Belegt heisst: ein anderer
  # Webserver steht im Weg, und Caddy bekäme den Port nicht.
  for port in 80 443 4444; do
    if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
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
    say "Plattform-CA steht bereits"
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
  # gerufen wird. Ein Name, der hier fehlt, lässt sich später nur mit einem
  # neuen Zertifikat nachtragen.
  local san="DNS:$KONSOLE_HOST,DNS:localhost,IP:127.0.0.1"
  [ "$BIND" != "127.0.0.1" ] && san="$san,IP:$BIND"
  if [ -n "$ZUSATZNAME" ]; then
    # IP oder Name? Die SAN-Einträge sind verschiedene Typen, und ein Name
    # im IP-Feld macht das Zertifikat still unbrauchbar.
    if printf '%s' "$ZUSATZNAME" | grep -qE '^[0-9]+(\.[0-9]+){3}$'; then
      san="$san,IP:$ZUSATZNAME"
    else
      san="$san,DNS:$ZUSATZNAME"
    fi
  fi
  zertifikat "console" "$KONSOLE_HOST" "$san"
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
  mkdir -p "$ZIEL"
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
PLATTFORM_NETZ=$NETZ
EOF
    chmod 600 "$konsole_env"
  else
    say "Umgebung der Konsole besteht bereits"
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
    say "Umgebung der Datenebene besteht bereits"
  fi
}

# --- Oberflächen -------------------------------------------------------------
build_ui() {
  command -v pnpm >/dev/null || return 0
  if [ ! -d "$REPO/cockpit/web/dist" ]; then
    say "Konsolen-Oberfläche bauen"
    (cd "$REPO/cockpit/web" && pnpm install --silent && pnpm build >/dev/null)
  else
    say "Konsolen-Oberfläche steht bereits ($REPO/cockpit/web/dist)"
  fi
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
  dc_konsole exec -T api alembic upgrade head >/dev/null
  warte "Konsole" "https://$KONSOLE_HOST:4444/api/health" --cert
}

start_daten() {
  say "Datenebene starten (Container, Kundenseiten auf 443)"
  if [ "$ZIEHEN" -eq 1 ]; then dc_daten pull --quiet; else dc_daten build --quiet; fi
  dc_daten up -d
}

warte() {  # $1 = Name, $2 = URL, $3 = --cert wenn Client-Zertifikat nötig
  local i=0 args=(-sS -o /dev/null --noproxy '*' -k
                  --resolve "$KONSOLE_HOST:4444:127.0.0.1")
  [ "${3:-}" = "--cert" ] && args+=(--cert "$CERTS/operator.pem" --key "$CERTS/operator-key.pem")
  while [ "$i" -lt 60 ]; do
    curl "${args[@]}" "$2" 2>/dev/null && { say "$1 antwortet"; return 0; }
    sleep 2; i=$((i+1))
  done
  die "$1 antwortet nicht. Logs: docker compose -f … logs"
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
        --resolve "$KONSOLE_HOST:4444:127.0.0.1"
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
       echo "127.0.0.1 $KONSOLE_HOST ${KUNDEN[0]}.$DOMAIN ${KUNDEN[1]}.$DOMAIN" >> /etc/hosts

  2. Konsole öffnen: https://$KONSOLE_HOST:4444
     Client-Zertifikat: $CERTS/operator.pem (+ -key.pem). Als PKCS#12 für
     den Browser:
       openssl pkcs12 -export -inkey $CERTS/operator-key.pem \\
         -in $CERTS/operator.pem -certfile $CERTS/platform-ca.pem \\
         -out $CERTS/operator.p12 -passout pass:dev

  3. Kundenseite öffnen: https://${KUNDEN[0]}.$DOMAIN
     (Die Plattform-CA $CERTS/root.pem im Browser als vertrauenswürdig
     eintragen, sonst warnt er — in Produktion kommt sie über die GPO.)

  4. Prüfen: die drei Handgriffe in
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
  rm -rf "$ZIEL" "$REPO/cockpit/deploy/certs" \
         "$REPO/cockpit/deploy/.env" "$REPO/deploy/compose/.env"
  say "Gelöscht — der nächste 'up' beginnt von vorn"
}

BEFEHL="${1:-up}"; shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --ziehen)  ZIEHEN=1; shift ;;
    --domaene) DOMAIN="$2"; KONSOLE_HOST="konsole.$DOMAIN"; shift 2 ;;
    --bind)    BIND="$2"; shift 2 ;;
    --zusatzname) ZUSATZNAME="$2"; shift 2 ;;
    *) die "Unbekannte Option: $1" ;;
  esac
done

case "$BEFEHL" in
  up)     cmd_up ;;
  status) cmd_status ;;
  down)   cmd_down ;;
  purge)  cmd_purge ;;
  *) die "Unbekannter Befehl: $BEFEHL (up, status, down, purge)" ;;
esac
