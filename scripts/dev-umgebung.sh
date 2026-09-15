#!/usr/bin/env bash
# Eine vollständige Magister-Entwicklungsumgebung auf einer Maschine.
#
#   ./scripts/dev-umgebung.sh up      # aufbauen und starten
#   ./scripts/dev-umgebung.sh status  # was läuft, was antwortet
#   ./scripts/dev-umgebung.sh down    # Prozesse beenden
#   ./scripts/dev-umgebung.sh purge   # Prozesse beenden UND alles löschen
#
# Was entsteht: eine Konsole (Control Plane) mit eigener Datenbank, ein
# Anwendungsserver (Data Plane) mit ZWEI Kunden in getrennten Schemas, eine
# Test-CA samt Operator- und Monitor-Zertifikat, und — wenn `caddy` da ist —
# beide Listener so, wie sie in Produktion stehen (Konsole auf 4444 mit
# Client-Zertifikat, Kundenseiten auf 8443 nach Hostname getrennt).
#
# **Kein Docker.** Absicht: die Dinge, die man in der Entwicklung anfasst
# (Migration, CLI, Logs, ein Breakpoint), sind ohne Container direkt greifbar.
# Für eine Einzelinstallation mit Docker gibt es `install-magister.sh --mode dev`;
# die deckt aber genau den Fall ab, den man beim Bauen der Plattform NICHT
# testen will: einen Mandanten, keine Konsole.
#
# **Die Test-CA ist eine Test-CA.** Sie entsteht hier auf der Platte, mit
# Schlüsseln ohne Passwort. Sie hat mit der Plattform-CA aus
# `docs/runbooks/platform-ca.md` nichts zu tun und darf nie eine Rolle
# ausserhalb dieses Verzeichnisses spielen.
#
# Voraussetzungen: uv, openssl, psql und ein erreichbares Postgres 16, in dem
# der angegebene Benutzer Datenbanken und Rollen anlegen darf. `caddy` und
# `age` sind optional; ohne sie fehlen die TLS-Listener beziehungsweise die
# Sicherungen.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV="${DEV_ROOT:-$REPO/dev}"
RUN="$DEV/run"
CERTS="$DEV/certs"
LOGS="$DEV/logs"

# Postgres, in dem beide Datenbanken entstehen. Der Benutzer braucht
# CREATEDB und CREATEROLE — die Konsole legt für jeden Kunden eine eigene
# Anmelderolle an (ADR-0013 D1).
PG_HOST="${DEV_PG_HOST:-localhost}"
PG_PORT="${DEV_PG_PORT:-5432}"
PG_USER="${DEV_PG_USER:-postgres}"
PG_PASSWORD="${DEV_PG_PASSWORD:-}"

CONSOLE_PORT="${DEV_CONSOLE_PORT:-8099}"   # Konsolen-API, nur auf 127.0.0.1
API_PORT="${DEV_API_PORT:-8000}"           # Datenebene, nur auf 127.0.0.1
CONSOLE_TLS_PORT="${DEV_CONSOLE_TLS_PORT:-4444}"
TENANT_TLS_PORT="${DEV_TENANT_TLS_PORT:-8443}"

# Zwei Kunden, weil ein Mandant fast jeden Mandantenfehler versteckt: der
# stille Fan-out, der fehlende Kundenschlüssel, der Scope, der nie greift.
TENANTS=("thun" "bern")

CONSOLE_HOST="console.mgmt.vitabrevis.dev"
say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m !  %s\033[0m\n' "$*"; }
die()  { printf '\033[31m !! %s\033[0m\n' "$*" >&2; exit 1; }

psql_admin() {
  PGPASSWORD="$PG_PASSWORD" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -v ON_ERROR_STOP=1 "$@"
}

pg_dsn() {  # $1 = Datenbank, $2 = Treiber (asyncpg oder leer)
  local db="$1" drv="${2:-}" auth="$PG_USER"
  [ -n "$PG_PASSWORD" ] && auth="$PG_USER:$PG_PASSWORD"
  if [ -n "$drv" ]; then
    echo "postgresql+$drv://$auth@$PG_HOST:$PG_PORT/$db"
  else
    echo "postgresql://$auth@$PG_HOST:$PG_PORT/$db"
  fi
}

dienst_muster() {  # $1 = Dienst -> Suchmuster für pgrep/pkill
  case "$1" in
    console) echo "uvicorn cockpit_api.main:app --host 127.0.0.1 --port $CONSOLE_PORT" ;;
    api)     echo "uvicorn magister_api.main:app --host 127.0.0.1 --port $API_PORT" ;;
    caddy)   echo "caddy run --config $DEV/Caddyfile" ;;
  esac
}

# Die PID-Datei hält den Prozess, den die Shell gestartet hat — `uv run` legt
# den echten Dienst darunter an und verschwindet. Deshalb nach dem Start die
# wirkliche PID nachtragen: sonst meldet `status` „aus", während der Dienst
# antwortet, und `down` lässt ihn stehen.
echte_pid() {  # $1 = Dienst
  local pid
  pid="$(pgrep -f "$(dienst_muster "$1")" | head -1)"
  [ -n "$pid" ] && echo "$pid" > "$RUN/$1.pid"
}

secret() { openssl rand -hex 32; }

# --- Voraussetzungen ---------------------------------------------------------
preflight() {
  for tool in uv openssl psql curl python3; do
    command -v "$tool" >/dev/null || die "$tool fehlt."
  done
  # Eine Zeile „nicht erreichbar" ist die teuerste Diagnose: sie deckt
  # „nicht installiert", „läuft nicht", „Rolle gibt es nicht" und „falsches
  # Passwort" ab, und jeder dieser Fälle braucht einen anderen Handgriff.
  # Deshalb hier unterscheiden — und sagen, was Postgres selbst gesagt hat.
  local pg_err
  if ! pg_err="$(psql_admin -d postgres -tc "select 1" 2>&1 >/dev/null)"; then
    printf '\033[31m !! Postgres unter %s:%s nicht erreichbar (Benutzer %s).\033[0m\n' \
      "$PG_HOST" "$PG_PORT" "$PG_USER" >&2
    [ -n "$pg_err" ] && printf '    Postgres sagt: %s\n' \
      "$(echo "$pg_err" | grep -v '^$' | head -2 | tr '\n' ' ')" >&2
    if (exec 3<>"/dev/tcp/$PG_HOST/$PG_PORT") 2>/dev/null; then
      exec 3<&- 3>&-
      cat >&2 <<HINWEIS

    Der Dienst hört auf dem Port — es scheitert die Anmeldung. Meist eines davon:

      * Die Rolle "$PG_USER" gibt es nicht. Welche es gibt, zeigt der
        Systembenutzer, dem der Cluster gehört:
            su - postgres -c "psql -c '\\du'"
        Dann mit dieser Rolle starten:
            DEV_PG_USER=<rolle> DEV_PG_PASSWORD=<passwort> ./scripts/dev-umgebung.sh up

      * Das Passwort fehlt. DEV_PG_PASSWORD=… voranstellen.

      * pg_hba.conf verlangt für 127.0.0.1 eine andere Methode (peer statt
        md5/scram). Das Skript verbindet sich über TCP, nicht über den Socket.
HINWEIS
    else
      cat >&2 <<HINWEIS

    Auf $PG_HOST:$PG_PORT hört nichts — es läuft kein Postgres. Einrichten:

        apt-get install -y postgresql-16
        systemctl enable --now postgresql

    Danach eine Anmelderolle anlegen, die CREATEDB und CREATEROLE darf (die
    Konsole legt für jeden Kunden eine eigene Rolle an, ADR-0013 D1):

        su - postgres -c "psql -c \"create role magdev login password 'magdev' createdb createrole\""

    und das Skript damit starten:

        DEV_PG_USER=magdev DEV_PG_PASSWORD=magdev ./scripts/dev-umgebung.sh up
HINWEIS
    fi
    exit 1
  fi
  command -v caddy >/dev/null || warn "caddy fehlt — die TLS-Listener werden übersprungen."
  command -v age   >/dev/null || warn "age fehlt — Sicherungen lassen sich nicht prüfen."

  # Belegte Ports sind der teuerste Fehler dieses Skripts: der neue Prozess
  # scheitert am `bind`, der ALTE antwortet weiter — mit den Geheimnissen von
  # gestern. Man sieht dann Antworten, die zu nichts passen („not_found" auf
  # eine Anfrage mit gültigem Marker). Deshalb hier abbrechen und nicht
  # hoffen. Gemessen: genau so passiert.
  local port name pid
  for paar in "console:$CONSOLE_PORT" "api:$API_PORT"; do
    name="${paar%%:*}"; port="${paar##*:}"
    (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null || continue
    exec 3<&- 3>&-
    # Der eigene Dienst aus einem früheren Lauf oder ein fremder? Das ist der
    # Unterschied zwischen „einmal down" und „hier stimmt etwas anderes
    # nicht" — und die Antwort steht in der Prozessliste, nicht im Kopf des
    # Bedieners.
    pid="$(pgrep -f "$(dienst_muster "$name")" | head -1)"
    if [ -n "$pid" ]; then
      die "Port $port hält die eigene $name aus einem früheren Lauf (PID $pid). Erst './scripts/dev-umgebung.sh down', dann 'up' erneut."
    fi
    die "Port $port ist belegt, aber nicht von Magister — dort hört ein fremder Dienst. Entweder ihn beenden oder mit DEV_${name^^}_PORT=<frei> starten."
  done
}

# --- Test-CA -----------------------------------------------------------------
# Dieselbe Form wie in Produktion: eine Wurzel, zwei Zwischenstellen
# (Operatoren, Connector). Ein einziges selbstsigniertes Zertifikat täte es
# für den Handshake auch — dann übt man aber nicht das Modell, das
# ADR-0020 und ADR-0014 tragen.
make_ca() {
  mkdir -p "$CERTS"
  [ -f "$CERTS/root.pem" ] && { say "CA steht bereits"; return; }
  say "Test-CA erzeugen"
  openssl req -x509 -newkey rsa:3072 -sha256 -days 825 -nodes -keyout "$CERTS/root-key.pem" \
    -out "$CERTS/root.pem" -subj "/CN=Magister DEV Root" \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null

  for kind in operator connector; do
    openssl req -newkey rsa:3072 -nodes -keyout "$CERTS/$kind-int-key.pem" \
      -out "$CERTS/$kind-int.csr" -subj "/CN=Magister DEV $kind Intermediate" 2>/dev/null
    openssl x509 -req -in "$CERTS/$kind-int.csr" -CA "$CERTS/root.pem" -CAkey "$CERTS/root-key.pem" \
      -CAcreateserial -days 730 -sha256 -out "$CERTS/$kind-int.pem" \
      -extfile <(printf 'basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\n') 2>/dev/null
  done
  cat "$CERTS/root.pem" "$CERTS/operator-int.pem" > "$CERTS/platform-ca.pem"

  # Serverzertifikat: der Konsolenname UND ein Wildcard für die Kundenseiten.
  # Wildcards gelten für genau eine Ebene — deshalb steht `*.mgmt…` hier
  # ausdrücklich neben `console.mgmt…`, wie in Produktion auch.
  openssl req -newkey rsa:3072 -nodes -keyout "$CERTS/server-key.pem" \
    -out "$CERTS/server.csr" -subj "/CN=$CONSOLE_HOST" 2>/dev/null
  openssl x509 -req -in "$CERTS/server.csr" -CA "$CERTS/root.pem" -CAkey "$CERTS/root-key.pem" \
    -CAcreateserial -days 730 -sha256 -out "$CERTS/server.pem" \
    -extfile <(printf 'subjectAltName=DNS:%s,DNS:*.mgmt.vitabrevis.dev,DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n' "$CONSOLE_HOST") 2>/dev/null

  # Zwei Client-Zertifikate: eine Person und die Überwachung. Der Monitor ist
  # bewusst KEINE Person und wird nicht als Operator eingetragen (ADR-0020 D4).
  for who in operator prtg-monitor; do
    openssl req -newkey rsa:3072 -nodes -keyout "$CERTS/$who-key.pem" \
      -out "$CERTS/$who.csr" -subj "/CN=$who" 2>/dev/null
    openssl x509 -req -in "$CERTS/$who.csr" -CA "$CERTS/operator-int.pem" \
      -CAkey "$CERTS/operator-int-key.pem" -CAcreateserial -days 730 -sha256 \
      -out "$CERTS/$who.pem" -extfile <(printf 'extendedKeyUsage=clientAuth\n') 2>/dev/null
  done

  # Ed25519 für die Einlösescheine des Operator-Zugriffs (ADR-0019).
  openssl genpkey -algorithm ed25519 -out "$CERTS/operator-signing.pem" 2>/dev/null

  # age-Schlüsselpaar für Sicherungen und Vor-Migrations-Dumps (ADR-0016 D2).
  # Ohne Empfänger verweigert die Welle den Start — richtig so, und in der
  # Entwicklung genauso ärgerlich wie in Produktion. Deshalb entsteht er hier.
  if command -v age-keygen >/dev/null; then
    age-keygen -o "$CERTS/backup-age.key" 2>"$CERTS/backup-age.pub"
    grep -o 'age1[0-9a-z]*' "$CERTS/backup-age.pub" | head -1 > "$CERTS/backup-age.recipient"
  fi
  chmod 600 "$CERTS"/*-key.pem "$CERTS/operator-signing.pem"
  [ -f "$CERTS/backup-age.key" ] && chmod 600 "$CERTS/backup-age.key"
}

# --- Datenbanken -------------------------------------------------------------
make_databases() {
  say "Datenbanken anlegen"
  for db in cockpit_dev magister_dev; do
    psql_admin -d postgres -tc "select 1 from pg_database where datname='$db'" | grep -q 1 \
      || psql_admin -d postgres -c "CREATE DATABASE $db" >/dev/null
  done
  # pgcrypto GEHÖRT hierher und nicht in die Bereitstellung: die Erweiterung
  # anzulegen ist ein Recht, das die Mandantenrolle nicht hat und nicht haben
  # soll. Ohne diese Zeile scheitert die erste Migration eines Kunden mit
  # „permission denied to create extension" — nachgemessen.
  for db in cockpit_dev magister_dev; do
    psql_admin -d "$db" -c "CREATE EXTENSION IF NOT EXISTS pgcrypto" >/dev/null
  done
}

# --- Umgebungsdateien --------------------------------------------------------
write_env() {
  say "Umgebung schreiben ($DEV/env.console, $DEV/env.dataplane)"
  mkdir -p "$DEV" "$RUN" "$LOGS" "$DEV/backups" "$DEV/exports" "$DEV/dumps"
  [ -f "$DEV/env.console" ] && return   # bestehende Geheimnisse nicht neu würfeln

  local head
  head="$(grep -oP 'HEAD_REVISION = "\K[^"]+' "$REPO/apps/api/magister_api/tenancy/version.py")"

  cat > "$DEV/env.console" <<EOF
# Konsole (Control Plane) — erzeugt von scripts/dev-umgebung.sh
export COCKPIT_DATABASE_URL="$(pg_dsn cockpit_dev asyncpg)"
export COCKPIT_BOOTSTRAP_TOKEN="$(secret)"
export COCKPIT_SECRET_KEY="$(openssl rand -base64 48 | tr -d '\n')"
export COCKPIT_MANAGEMENT_MARKER="$(secret)"
export COCKPIT_CONNECTOR_MARKER="$(secret)"
export COCKPIT_REQUIRE_MANAGEMENT_LISTENER="1"
export COCKPIT_PUBLISHED_ADDRESS="127.0.0.1:$CONSOLE_TLS_PORT"
export COCKPIT_TENANT_ADMIN_DSN="$(pg_dsn magister_dev asyncpg)"
export COCKPIT_MAGISTER_API_DIR="$REPO/apps/api"
export COCKPIT_EXPECTED_SCHEMA_VERSION="$head"
export COCKPIT_CONNECTOR_CA_CERT="$CERTS/connector-int.pem"
export COCKPIT_CONNECTOR_CA_KEY="$CERTS/connector-int-key.pem"
export COCKPIT_OPERATOR_SIGNING_KEY="$CERTS/operator-signing.pem"
export COCKPIT_BACKUP_AGE_RECIPIENT="$(cat "$CERTS/backup-age.recipient" 2>/dev/null || echo '')"
export COCKPIT_BACKUP_SHARE_ROOT="$DEV/backups"
export COCKPIT_EXPORT_ROOT="$DEV/exports"
EOF

  cat > "$DEV/env.dataplane" <<EOF
# Datenebene (Data Plane) — erzeugt von scripts/dev-umgebung.sh
export MAGISTER_ENVIRONMENT="development"
export MAGISTER_DATABASE_URL="$(pg_dsn magister_dev asyncpg)"
export MAGISTER_AUDIT_KEY="$(secret)"
export MAGISTER_SESSION_SECRET="$(secret)"
export MAGISTER_CSRF_SECRET="$(secret)"
export MAGISTER_SESSION_COOKIE_SECURE="false"
# Verzeichnis: ldap3-Mock statt eines echten DC. Damit laufen Abgleich und
# Passwort-Reset ohne Domäne — was sie NICHT prüfen, ist das echte AD.
export MAGISTER_AD_USE_MOCK="1"
export MAGISTER_AD_USERS_SEARCH_BASE="DC=schule,DC=local"
export MAGISTER_AD_SYNC_INTERVAL_MINUTES="5"
export MAGISTER_HEALTH_TOKEN="$(secret)"
# Empfänger für Dumps und Sicherungen; der private Teil liegt daneben in
# $CERTS/backup-age.key (nur Entwicklung — in Produktion nie auf demselben Host).
export MAGISTER_BACKUP_AGE_RECIPIENT="$(cat "$CERTS/backup-age.recipient" 2>/dev/null || echo '')"
EOF
  chmod 600 "$DEV/env.console" "$DEV/env.dataplane"
}

# --- Konsole -----------------------------------------------------------------
# `--extra dev` und nicht ein blankes `uv sync`: das entfernt pytest, httpx
# und die übrigen Entwicklungsabhängigkeiten aus dem venv — und danach
# scheitert der nächste Testlauf mit „No module named httpx" an einer Stelle,
# die mit den Tests nichts zu tun hat. Genau so passiert, beim ersten Lauf
# dieses Skripts.
start_console() {
  # shellcheck disable=SC1091
  source "$DEV/env.console"
  say "Konsolen-Schema migrieren"
  (cd "$REPO/cockpit/api" && uv sync --quiet --extra dev && uv run alembic upgrade head >/dev/null)

  say "Konsole starten (127.0.0.1:$CONSOLE_PORT)"
  # `setsid`: eigene Prozessgruppe. Ohne das nimmt ein Aufrufer, der selbst
  # beendet wird (CI-Schritt, Hintergrundlauf, geschlossenes Terminal), die
  # Dienste mit — und `status` meldet danach „aus", obwohl gerade alles
  # aufgebaut wurde. Gemessen.
  # `disown -a`: eine Subshell wartet beim Verlassen auf ihre Hintergrund-
  # aufträge — anders als die Hauptshell. Ohne das kehrt `up` nach getaner
  # Arbeit nie zurück, weil es auf den Dienst wartet, den es gerade gestartet
  # hat. Gemessen: die Umgebung stand vollständig, das Skript hing trotzdem.
  (cd "$REPO/cockpit/api" && setsid nohup uv run uvicorn cockpit_api.main:app \
      --host 127.0.0.1 --port "$CONSOLE_PORT" > "$LOGS/console.log" 2>&1 < /dev/null &
      echo $! > "$RUN/console.pid"; disown -a)
  wait_for "http://127.0.0.1:$CONSOLE_PORT/api/health" "Konsole" "$LOGS/console.log"
  echte_pid console
}

console_api() {  # $1 = Methode, $2 = Pfad, $3 = Rumpf (optional)
  # shellcheck disable=SC1091
  source "$DEV/env.console"
  local args=(-sS -X "$1" "http://127.0.0.1:$CONSOLE_PORT$2"
    -H "Authorization: Bearer $COCKPIT_BOOTSTRAP_TOKEN"
    -H "X-Magister-Management: $COCKPIT_MANAGEMENT_MARKER")
  [ $# -ge 3 ] && args+=(-H "Content-Type: application/json" -d "$3")
  curl "${args[@]}"
}

# --- Kunden ------------------------------------------------------------------
# Zwei Kunden über die API, nicht über SQL: so läuft die echte Bereitstellung
# (Rolle, Schema, Migration, Kundenschlüssel, Freischalten) und man sieht im
# Auftragsprotokoll, wo sie hängen bliebe.
make_tenants() {
  # shellcheck disable=SC1091
  source "$DEV/env.dataplane"
  local out list id
  for slug in "${TENANTS[@]}"; do
    list="$(console_api GET "/api/tenants")"
    if echo "$list" | grep -q "\"slug\":\"$slug\""; then
      # Da, aber fertig? Ein Kunde ohne Schemastand ist in der Bereitstellung
      # steckengeblieben (so geschehen, als der Verwaltungszugang kein SET
      # ROLE durfte). Ihn dann als „besteht bereits" zu überspringen, macht
      # aus einem Fehler einen Dauerzustand — und aus einem roten Prüflauf
      # siebzehn.
      id="$(echo "$list" | python3 -c '
import json, sys
liste = json.loads(sys.stdin.read().rsplit("\n", 1)[0])
for t in liste:
    if t["slug"] == sys.argv[1] and not t.get("schema_version"):
        print(t["id"])
' "$slug" 2>/dev/null)"
      if [ -z "$id" ]; then
        say "Kunde $slug besteht bereits"
        continue
      fi
      say "Kunde $slug ist halb bereitgestellt — Auftrag fortsetzen"
      out="$(console_api POST "/api/tenants/$id/provisioning/resume")"
    else
      say "Kunde $slug bereitstellen"
      out="$(console_api POST "/api/tenants" \
        "{\"slug\":\"$slug\",\"name\":\"${slug^} (dev)\",\"hostname\":\"$slug.mgmt.vitabrevis.dev\"}")"
    fi
    if ! python3 - "$out" "$DEV/env.dataplane" <<'PY'
import json, re, sys, pathlib

data = json.loads(sys.argv[1])
tenant, job = data["tenant"], data["job"]
# ZWEI Bezeichner, und sie sind nicht dasselbe: der DSN hängt am
# `dsn_ref` (`MAGISTER_TENANT_DSN_TENANT_THUN`), die drei Schlüssel am
# **Slug** (`MAGISTER_TENANT_AUDIT_KEY_THUN`). Beim ersten Lauf dieses
# Skripts standen überall Refs — die Datenebene fand die Schlüssel nicht
# und bediente beide Kunden mit Wartung.
ref = tenant["dsn_ref"].upper()
slug_ref = tenant["slug"].upper().replace("-", "_")
failed = [s for s in job["steps"] if not s["ok"]]

# Zusammenführen statt anhängen: ein fortgesetzter Auftrag bringt nur die
# Geheimnisse der Schritte mit, die er wirklich ausgeführt hat. Wurde die
# Rolle in einem früheren Lauf angelegt, ist `role_password` leer — das
# vorhandene DSN gilt dann weiter und darf nicht mit „None" überschrieben
# werden.
neu: dict[str, str] = {}
if data.get("role_password"):
    neu[f"MAGISTER_TENANT_DSN_{ref}"] = (
        f"__DSN__:{tenant['db_role']}:{data['role_password']}:{tenant['schema_name']}"
    )
if data.get("data_key"):
    neu[f"MAGISTER_TENANT_AUDIT_KEY_{slug_ref}"] = data["data_key"]
    neu[f"MAGISTER_TENANT_AUDIT_KEY_ID_{slug_ref}"] = f"{tenant['slug']}-dev"
    neu[f"MAGISTER_TENANT_SECRETS_KEY_{slug_ref}"] = data["data_key"]

env = pathlib.Path(sys.argv[2])
inhalt = env.read_text()
vorhanden = dict(re.findall(r'^export (MAGISTER_TENANT_\w+)="([^"]*)"$', inhalt, re.M))
namen = [
    f"MAGISTER_TENANT_DSN_{ref}",
    f"MAGISTER_TENANT_AUDIT_KEY_{slug_ref}",
    f"MAGISTER_TENANT_AUDIT_KEY_ID_{slug_ref}",
    f"MAGISTER_TENANT_SECRETS_KEY_{slug_ref}",
]
werte = {name: neu.get(name, vorhanden.get(name, "")) for name in namen}

# Alte Zeilen dieses Kunden entfernen, dann einen sauberen Block schreiben.
inhalt = re.sub(rf"\n?# --- Kunde {tenant['slug']} ---\n", "\n", inhalt)
for name in namen:
    inhalt = re.sub(rf'^export {name}="[^"]*"\n', "", inhalt, flags=re.M)
zeilen = [f"# --- Kunde {tenant['slug']} ---"]
zeilen += [f'export {name}="{werte[name]}"' for name in namen if werte[name]]
env.write_text(inhalt.rstrip("\n") + "\n\n" + "\n".join(zeilen) + "\n")

print(f"  {tenant['slug']}: Schema {tenant['schema_name']}, Rolle {tenant['db_role']}, "
      f"Stand {tenant['schema_version'] or 'keiner'}")
if failed:
    # Abbrechen statt weiterlaufen. Eine halbe Bereitstellung trägt sich
    # durch alles Folgende: die Datenebene startet nicht, und der Prüfer
    # meldet siebzehn rote Zeilen, die alle denselben einen Grund haben.
    print(f"\n  ! Bereitstellung von {tenant['slug']} hing bei "
          f"{failed[0]['step']}: {failed[0]['detail']}")
    sys.exit(3)
PY
    then
      die "Bereitstellung unvollständig. Ursache oben beheben, dann erneut './scripts/dev-umgebung.sh up' — der Auftrag wird ab der Abbruchstelle fortgesetzt."
    fi
  done
  # Den Platzhalter durch den echten DSN ersetzen: das Rollenpasswort kommt
  # aus der Antwort und darf nicht durch eine Shell-Interpolation laufen.
  python3 - "$DEV/env.dataplane" "$PG_HOST" "$PG_PORT" <<'PY'
import re, sys, pathlib
env = pathlib.Path(sys.argv[1]); host, port = sys.argv[2], sys.argv[3]
def fix(m: re.Match[str]) -> str:
    role, password, _schema = m.group(1), m.group(2), m.group(3)
    return f'postgresql+asyncpg://{role}:{password}@{host}:{port}/magister_dev'
env.write_text(re.sub(r"__DSN__:([^:]+):([^:]+):([^\"]+)", fix, env.read_text()))
PY
}

# --- Datenebene --------------------------------------------------------------
start_dataplane() {
  # shellcheck disable=SC1091
  source "$DEV/env.console"
  # shellcheck disable=SC1091
  source "$DEV/env.dataplane"
  export MAGISTER_CONSOLE_REGISTRY_URL="http://127.0.0.1:$CONSOLE_PORT/api/tenants/registry"
  export MAGISTER_CONSOLE_REGISTRY_TOKEN="$COCKPIT_BOOTSTRAP_TOKEN"
  export MAGISTER_CONSOLE_MANAGEMENT_MARKER="$COCKPIT_MANAGEMENT_MARKER"
  export MAGISTER_AD_CONNECTOR_ENABLED="1"
  # In Produktion holt die Datenebene die Registry alle 300 s. Für die
  # Entwicklung ist das der kleinste erlaubte Takt: sonst wartet, wer eine
  # Änderung in der Konsole prüfen will, fünf Minuten auf ihre Wirkung.
  export MAGISTER_CONSOLE_REGISTRY_INTERVAL_S="30"
  # Erst die Zeilen eines früheren Laufs entfernen: `up` ist wiederholbar, und
  # eine Umgebungsdatei, die bei jedem Lauf wächst, führt irgendwann ein
  # veraltetes Token mit sich, das weiter unten das aktuelle überschreibt.
  local tmp="$DEV/env.dataplane.tmp"
  grep -v -E '^export MAGISTER_(CONSOLE_REGISTRY_URL|CONSOLE_REGISTRY_TOKEN|CONSOLE_MANAGEMENT_MARKER|AD_CONNECTOR_ENABLED|CONSOLE_REGISTRY_INTERVAL_S)=' \
    "$DEV/env.dataplane" > "$tmp"
  {
    echo "export MAGISTER_CONSOLE_REGISTRY_URL=\"$MAGISTER_CONSOLE_REGISTRY_URL\""
    echo "export MAGISTER_CONSOLE_REGISTRY_TOKEN=\"$MAGISTER_CONSOLE_REGISTRY_TOKEN\""
    echo "export MAGISTER_CONSOLE_MANAGEMENT_MARKER=\"$MAGISTER_CONSOLE_MANAGEMENT_MARKER\""
    echo "export MAGISTER_AD_CONNECTOR_ENABLED=\"1\""
    echo "export MAGISTER_CONSOLE_REGISTRY_INTERVAL_S=\"30\""
  } >> "$tmp"
  mv "$tmp" "$DEV/env.dataplane"
  chmod 600 "$DEV/env.dataplane"

  say "Datenebene starten (127.0.0.1:$API_PORT)"
  (cd "$REPO/apps/api" && uv sync --quiet --extra dev && setsid nohup uv run uvicorn magister_api.main:app \
      --host 127.0.0.1 --port "$API_PORT" > "$LOGS/api.log" 2>&1 < /dev/null &
      echo $! > "$RUN/api.pid"; disown -a)
  wait_for "http://127.0.0.1:$API_PORT/healthz" "Datenebene" "$LOGS/api.log"
  echte_pid api
}

seed() {
  # shellcheck disable=SC1091
  source "$DEV/env.dataplane"
  for slug in "${TENANTS[@]}"; do
    local ref dsn
    ref="TENANT_${slug^^}"
    dsn="$(eval echo "\${MAGISTER_TENANT_DSN_$ref:-}")"
    [ -z "$dsn" ] && { warn "kein DSN für $slug — Demodaten übersprungen"; continue; }
    say "Demodaten für $slug"
    # Ein zweiter Lauf von `up` darf nicht scheitern: der Seeder weigert sich
    # zu Recht, in eine Datenbank zu schreiben, in der schon Klassen stehen.
    # Ohne diese Behandlung bricht `set -e` den ganzen Aufbau ab — und zwar
    # NACH der Datenebene und VOR Caddy, also mitten im Stapel. Gemessen.
    local out rc
    out="$(cd "$REPO/apps/api" && MAGISTER_DATABASE_URL="$dsn" \
      uv run python -m magister_api.cli.seed_demo --schema "t_$slug" 2>&1)" && rc=0 || rc=$?
    if [ "$rc" -eq 0 ]; then
      printf '  %s\n' "$(echo "$out" | tail -1)"
    elif echo "$out" | grep -q "already contains classes"; then
      printf '  %s\n' "Demodaten stehen bereits."
    else
      warn "Demodaten für $slug: $(echo "$out" | tail -1)"
    fi
  done
}

# --- Caddy -------------------------------------------------------------------
start_caddy() {
  command -v caddy >/dev/null || return 0
  # shellcheck disable=SC1091
  source "$DEV/env.console"
  cat > "$DEV/Caddyfile" <<EOF
{
	auto_https off
	admin off
	# Ohne SNI (Aufruf über die IP) wüsste Caddy nicht, welches Zertifikat
	# gilt, und antwortet mit 421. In Produktion steht hier derselbe
	# Handgriff aus demselben Grund.
	default_sni $CONSOLE_HOST
}

# Konsole: Client-Zertifikat Pflicht (ADR-0020 D1) — genau wie in Produktion.
# Zwei Namen, damit sowohl der Browser (Hostname) als auch ein curl auf
# 127.0.0.1 hereinkommt.
https://$CONSOLE_HOST:$CONSOLE_TLS_PORT, https://127.0.0.1:$CONSOLE_TLS_PORT {
	tls $CERTS/server.pem $CERTS/server-key.pem {
		client_auth {
			mode require_and_verify
			trust_pool file $CERTS/platform-ca.pem
		}
	}
	handle /api/* {
		reverse_proxy 127.0.0.1:$CONSOLE_PORT {
			header_up X-Magister-Management "$COCKPIT_MANAGEMENT_MARKER"
			header_up X-Console-Client-Cert {http.request.tls.client.certificate_der_base64}
		}
	}
	handle {
		root * $REPO/cockpit/web/dist
		try_files {path} /index.html
		file_server
	}
}

# Kundenseiten: ein Block für alle, getrennt wird nach Hostname — dieselbe
# Auflösung wie in Produktion (ADR-0013 D3).
https://:$TENANT_TLS_PORT {
	tls $CERTS/server.pem $CERTS/server-key.pem
	handle /healthz* {
		reverse_proxy 127.0.0.1:$API_PORT {
			header_up X-Forwarded-Host {host}
		}
	}
	handle_path /api/* {
		reverse_proxy 127.0.0.1:$API_PORT {
			header_up X-Forwarded-Host {host}
			header_up X-Forwarded-Proto {scheme}
		}
	}
	handle {
		root * $REPO/apps/web/dist
		try_files {path} /index.html
		file_server
	}
}
EOF
  say "Caddy starten (Konsole $CONSOLE_TLS_PORT, Kunden $TENANT_TLS_PORT)"
  setsid nohup caddy run --config "$DEV/Caddyfile" > "$LOGS/caddy.log" 2>&1 < /dev/null &
  echo $! > "$RUN/caddy.pid"
  disown -a
  sleep 2
  echte_pid caddy
}

wait_for() {  # $1 = URL, $2 = Name, $3 = Logdatei (optional)
  for _ in $(seq 1 40); do
    curl -sS -o /dev/null "$1" 2>/dev/null && { say "$2 antwortet"; return 0; }
    sleep 0.5
  done
  # Den Grund gleich mitliefern. „Siehe $LOGS" verlangt einen zweiten
  # Handgriff für etwas, das das Skript schon vor sich hat — und die letzte
  # Zeile des Logs ist fast immer die Antwort.
  if [ -n "${3:-}" ] && [ -s "$3" ]; then
    printf '\033[31m !! %s antwortet nicht. Letzte Zeilen aus %s:\033[0m\n' "$2" "$3" >&2
    tail -15 "$3" >&2
    exit 1
  fi
  die "$2 antwortet nicht — siehe $LOGS."
}

# --- Befehle -----------------------------------------------------------------
cmd_up() {
  preflight
  make_ca
  make_databases
  write_env
  start_console
  make_tenants
  start_dataplane
  seed
  start_caddy
  cmd_status
  cat <<EOF

$(printf '\033[1mNächste Schritte\033[0m')

  1. Namen auflösbar machen (einmalig, als root):
       echo "127.0.0.1 $CONSOLE_HOST ${TENANTS[0]}.mgmt.vitabrevis.dev ${TENANTS[1]}.mgmt.vitabrevis.dev" >> /etc/hosts

  2. Oberflächen bauen, falls noch nicht geschehen:
       (cd $REPO/cockpit/web && pnpm install && pnpm build)
       (cd $REPO/apps/web     && pnpm install && pnpm build)

  3. Konsole öffnen: https://$CONSOLE_HOST:$CONSOLE_TLS_PORT
     Das Client-Zertifikat liegt in $CERTS/operator.pem (+ -key.pem);
     als PKCS#12 für den Browser:
       openssl pkcs12 -export -inkey $CERTS/operator-key.pem \\
         -in $CERTS/operator.pem -certfile $CERTS/platform-ca.pem \\
         -out $CERTS/operator.p12 -passout pass:dev

  4. Der Prüfplan steht in docs/runbooks/dev-testumgebung.md.
EOF
}

cmd_status() {
  # shellcheck disable=SC1091
  source "$DEV/env.dataplane" 2>/dev/null || true
  say "Zustand"
  for name in console api caddy; do
    local pid_file="$RUN/$name.pid" pid=""
    if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
      printf '  %-8s läuft (PID %s)\n' "$name" "$(cat "$pid_file")"
    elif pid="$(pgrep -f "$(dienst_muster "$name")" | head -1)"; [ -n "$pid" ]; then
      printf '  %-8s läuft (PID %s, PID-Datei war veraltet)\n' "$name" "$pid"
      echo "$pid" > "$pid_file"
    else
      printf '  %-8s aus\n' "$name"
    fi
  done
  local body
  for slug in "${TENANTS[@]}"; do
    body="$(curl -sS -H "X-Magister-Health: ${MAGISTER_HEALTH_TOKEN:-}" \
      -H "Host: $slug.mgmt.vitabrevis.dev" \
      "http://127.0.0.1:$API_PORT/healthz/stack" 2>/dev/null || true)"
    # Die Antwort als ARGUMENT und der Parser als Heredoc: eine Fassung mit
    # `python3 -c` in einer Zeile hatte verschachtelte Anführungszeichen, die
    # die Shell frass — die Sonde antwortete, und hier stand trotzdem
    # „keine Antwort".
    python3 - "$slug" "$body" <<'PY'
import json, sys

slug, raw = sys.argv[1], sys.argv[2]
try:
    data = json.loads(raw)
except Exception:
    print(f"  {slug:<8} keine Antwort")
    raise SystemExit
checks = data.get("checks")
if not isinstance(checks, list):
    # Gültiges JSON, aber nicht die Sonde: z.B. `{"detail":"Not Found"}`,
    # wenn der Token fehlt. Ein KeyError wäre hier ein Stacktrace als
    # Statusanzeige.
    print(f"  {slug:<8} unerwartete Antwort: {raw[:60]}")
    raise SystemExit
bad = [c for c in checks if c["status"]]
detail = "; ".join(f"{c['name']}: {c['detail']}" for c in bad)
line = f"  {slug:<8} Stufe {data['status']} ({data['state']})"
print(line + (f" — {detail}" if detail else ""))
PY
  done
}

cmd_down() {
  # Erst die Muster, dann die PID-Dateien: `uv run` startet uvicorn als Kind,
  # und eine PID-Datei kann veraltet sein (Neustart der Maschine, von Hand
  # gestartete Prozesse). Die Muster nennen Port und Modul, treffen also
  # genau diese Umgebung und nicht irgendein fremdes uvicorn.
  for name in console api caddy; do
    pkill -f "$(dienst_muster "$name")" 2>/dev/null || true
  done
  for name in caddy api console; do
    local pid_file="$RUN/$name.pid"
    [ -f "$pid_file" ] || continue
    # Die ganze Gruppe: `uv run` startet uvicorn als Kind, und ein Kill nur
    # auf den Elternprozess liesse den Port belegt.
    kill -- "-$(cat "$pid_file")" 2>/dev/null || kill "$(cat "$pid_file")" 2>/dev/null || true
    rm -f "$pid_file"
  done
  say "Prozesse beendet (Daten und Geheimnisse bleiben in $DEV)"
}

cmd_purge() {
  cmd_down
  say "Datenbanken und $DEV löschen"
  for db in cockpit_dev magister_dev; do
    psql_admin -d postgres -c "DROP DATABASE IF EXISTS $db WITH (FORCE)" >/dev/null 2>&1 || true
  done
  for slug in "${TENANTS[@]}"; do
    psql_admin -d postgres -c "DROP ROLE IF EXISTS r_$slug" >/dev/null 2>&1 || true
  done
  rm -rf "$DEV"

  # Nachsehen, ob wirklich weg. Die Löschungen oben schlucken ihre Fehler —
  # das ist bequem, aber wer „purge" sagt, will von vorn anfangen und nicht
  # mit einer übriggebliebenen Rolle weiterarbeiten, die dann beim nächsten
  # Aufbau ein Passwort von gestern trägt.
  local rest=""
  for db in cockpit_dev magister_dev; do
    psql_admin -d postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname = '$db'" 2>/dev/null | grep -q 1 \
      && rest="$rest  Datenbank $db\n"
  done
  for slug in "${TENANTS[@]}"; do
    psql_admin -d postgres -tAc \
      "SELECT 1 FROM pg_roles WHERE rolname = 'r_$slug'" 2>/dev/null | grep -q 1 \
      && rest="$rest  Rolle r_$slug\n"
  done
  if [ -n "$rest" ]; then
    warn "Das liess sich nicht löschen — der nächste Aufbau startet also nicht ganz von vorn:"
    printf "$rest" >&2
    cat >&2 <<HINWEIS
    Meist hängt daran noch etwas: eine offene Verbindung, oder ein Objekt in
    einer anderen Datenbank desselben Clusters. Was genau, sagt:
        psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d postgres -c 'DROP ROLE r_${TENANTS[0]}'
HINWEIS
  else
    say "Alles gelöscht — der nächste 'up' beginnt von vorn"
  fi
}

case "${1:-up}" in
  up)     cmd_up ;;
  status) cmd_status ;;
  down)   cmd_down ;;
  purge)  cmd_purge ;;
  *) die "Unbekannter Befehl: $1 (up | status | down | purge)" ;;
esac
