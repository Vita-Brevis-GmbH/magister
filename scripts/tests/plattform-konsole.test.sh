#!/usr/bin/env bash
# plattform-aufbau.sh ↔ scripts/cockpit.sh der Konsole (vitabrevis-cockpit,
# ADR 0009 dort): die Schnittstelle von der Seite des Aufrufers.
#
# Warum es diesen Test gibt: seit die Konsole sich selbst aufbaut, ruft `up`
# hier nur noch ihr Skript auf. Was beide brauchen – Rollenpasswort der
# Datenebene, Bootstrap-Token, Marker, Plattform-CA, Netz – muss dabei auf
# beiden Seiten gleich ankommen, sonst bekommt die Datenebene keinen Kunden
# oder die Konsole keine Rolle. Und ein Update muss genau das tun, was es vor
# dem Umbau tat: nichts neu erzeugen, was schon da ist.
#
# Zwei Durchgänge, beide ohne Docker und ohne Netz (Attrappen für docker,
# curl, getent, systemctl, ss, sleep; openssl ist echt):
#
#   A  mit einer Attrappe für scripts/cockpit.sh – was Magister übergibt;
#   B  mit dem echten scripts/cockpit.sh aus einem Checkout von
#      vitabrevis-cockpit (MAGISTER_TEST_KONSOLE_DIR, sonst
#      ../vitabrevis-cockpit). Fehlt er oder ist er zu alt, wird B
#      übersprungen und das gesagt.
#
#   ./scripts/tests/plattform-konsole.test.sh

set -uo pipefail
unset PLATTFORM_KONSOLE PLATTFORM_KONF COMPOSE_FILE KONSOLE_SETZEN KONSOLE_STARTWERTE MAGISTER_DIR

ECHT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

GRUEN=0
ROT=0
pruefe() {  # $1 = Beschreibung, $2 = erwartet, $3 = tatsächlich
  if [ "$2" = "$3" ]; then
    printf '\033[32m  ok  \033[0m%s\n' "$1"
    GRUEN=$((GRUEN + 1))
  else
    printf '\033[31m  !!  %s\033[0m\n      erwartet: %s\n      erhalten: %s\n' "$1" "$2" "$3"
    ROT=$((ROT + 1))
  fi
}
ja_wenn() { if "$@"; then echo ja; else echo nein; fi; }
wert() { grep -m1 "^$1=" "$2" 2>/dev/null | cut -d= -f2-; }

# --- Ein Magister-Repo, so weit `up` es braucht -------------------------------
neues_repo() {  # $1 = Ziel
  mkdir -p "$1/scripts/lib" "$1/deploy/compose" "$1/apps/api/magister_api/tenancy"
  cp "$ECHT/scripts/plattform-aufbau.sh" "$1/scripts/"
  cp "$ECHT/scripts/lib/konsole-pfad.sh" "$1/scripts/lib/"
  cp "$ECHT/apps/api/magister_api/tenancy/version.py" "$1/apps/api/magister_api/tenancy/"
}
KOPF="$(grep -oE '"[0-9]{4}_[a-z_]+"' "$ECHT/apps/api/magister_api/tenancy/version.py" | head -1 | tr -d '"')"

# --- Attrappen ----------------------------------------------------------------
mkdir -p "$T/bin"
cat > "$T/bin/docker" <<'X'
#!/usr/bin/env bash
echo "MAGISTER_DIR=${MAGISTER_DIR:-} docker $*" >> "$AUFRUFE"
case "${1:-} ${2:-}" in
  "compose version"|"info ") exit 0 ;;
  "volume inspect") [ -f "$DZ/vol/$3" ]; exit $? ;;
  "volume ls") exit 0 ;;
  "network inspect") [ -f "$DZ/netz/$3" ]; exit $? ;;
  "network create") touch "$DZ/netz/$3"; exit 0 ;;
  "ps --filter") exit 0 ;;
esac
if [ "${1:-}" = compose ]; then
  case "$*" in
    *" ps --format "*) echo "  dienst  Up 1 minute" ;;
    *" exec -T magister-api python -c "*) echo "$KOPF" ;;
    *" exec -T postgres psql "*) echo 0 ;;
    *" up -d"*) [ -f "$DZ/vol/cockpit_cockpit-pg" ] || echo x > "$DZ/vol/cockpit_cockpit-pg" ;;
  esac
fi
exit 0
X
cat > "$T/bin/curl" <<'X'
#!/usr/bin/env bash
echo "curl $*" >> "$AUFRUFE"
url="${*: -1}"
for a in "$@"; do case "$a" in https://*) url="$a" ;; esac; done
case "$url" in
  */api/health) exit 0 ;;
  */api/tenants)
    printf '[{"slug":"kunde_a","id":"11111111-1111-4111-8111-111111111111","dsn_ref":"tenant_kunde_a","db_role":"r_kunde_a","schema_name":"t_kunde_a","audit_key_id":"kunde_a-1","status":"active","schema_version":"%s","hostname":"kunde-a.example.ch"}]\n200' "$KOPF" ;;
  */rotate-role-password) printf '{"role_password":"pw-kunde-a"}\n200' ;;
  */healthz/stack) printf '{"status":0,"checks":[]}' ;;
esac
exit 0
X
printf '#!/usr/bin/env bash\nexit 2\n' > "$T/bin/getent"
for w in systemctl sysctl sleep; do printf '#!/usr/bin/env bash\nexit 0\n' > "$T/bin/$w"; done
printf '#!/usr/bin/env bash\nexit 0\n' > "$T/bin/ss"
chmod +x "$T/bin/"*

lauf() {  # $1 = Repo, Rest = Argumente -> Ausgabe
  local repo="$1"; shift
  env -u PLATTFORM_DOMAIN -u PLATTFORM_BIND -u PLATTFORM_ZUSATZNAME \
      -u PLATTFORM_ART -u PLATTFORM_TLS -u PLATTFORM_ACME_MAIL -u PLATTFORM_WAF \
      -u GITHUB_TOKEN \
      PATH="$T/bin:$PATH" HOME="$T/home" AUFRUFE="$AUFRUFE" DZ="$DZ" KOPF="$KOPF" \
      PLATTFORM_ROOT="$repo/plattform" PLATTFORM_NICHT_FRAGEN=1 \
      "${UMGEBUNG[@]}" bash "$repo/scripts/plattform-aufbau.sh" "$@" 2>&1
}
UMGEBUNG=()
ERSTES_UP=(up --domaene example.ch --bind 127.0.0.1 --zusatzname host01.example.ch --art test --tls plattform-ca)

# =============================================================================
printf '\n\033[1mA · Was Magister an scripts/cockpit.sh übergibt (Attrappe)\033[0m\n'
REPO_A="$T/a/magister"; KONSOLE_A="$T/a/cockpit"
neues_repo "$REPO_A"
mkdir -p "$KONSOLE_A/deploy" "$KONSOLE_A/scripts" "$T/home"
printf 'name: cockpit\nservices: {}\n' > "$KONSOLE_A/deploy/docker-compose.yml"
# Die Attrappe schreibt Aufrufe und Umgebung mit und führt eine .env wie die
# echte: neu aus den Startwerten, sonst bleibt sie.
cat > "$KONSOLE_A/scripts/cockpit.sh" <<'ATTRAPPE'
#!/usr/bin/env bash
w="$(cd "$(dirname "$0")/.." && pwd)"
echo "cockpit.sh $* MAGISTER_DIR=${MAGISTER_DIR:-}" >> "$AUFRUFE"
case "${1:-}" in
  schnittstelle) echo 1 ;;
  up)
    [ -z "${KONSOLE_UP_SCHEITERT:-}" ] || { echo " !! Konsole antwortet nicht (Attrappe)" >&2; exit 1; }
    printf '%s\n' "${KONSOLE_SETZEN:-}" > "$DZ/setzen"
    printf '%s\n' "${KONSOLE_STARTWERTE:-}" > "$DZ/startwerte"
    if [ ! -f "$w/deploy/.env" ]; then
      { grep '^COCKPIT_TENANT_ADMIN_DSN=' <<<"$KONSOLE_STARTWERTE"
        echo "COCKPIT_BOOTSTRAP_TOKEN=token-der-konsole"
        echo "COCKPIT_MANAGEMENT_MARKER=marker-der-konsole"; } > "$w/deploy/.env"
    fi ;;
  wert) grep -m1 "^$2=" "$w/deploy/.env" | cut -d= -f2- ;;
  operatoren-zahl) echo 0 ;;
  status) echo "  konsole  api  Up 1 minute" ;;
esac
exit 0
ATTRAPPE
DZ="$T/a/dz"; AUFRUFE="$T/a/aufrufe"
mkdir -p "$DZ/vol" "$DZ/netz"
UMGEBUNG=(PLATTFORM_KONSOLE="$KONSOLE_A")
A="$(lauf "$REPO_A" "${ERSTES_UP[@]}")"; rc=$?
pruefe "up läuft durch"                          "0" "$rc"
pruefe "die Konsole einmal aufgebaut, mit Magister" "1" "$(grep -c "^cockpit.sh up  *MAGISTER_DIR=$REPO_A$" "$AUFRUFE")"
pruefe "KONSOLE_SETZEN: Adressen und Orte" "COCKPIT_BIND_ADDRESS=127.0.0.1
COCKPIT_HOSTNAME=konsole.example.ch
COCKPIT_CONNECTOR_HOSTNAME=connect.example.ch
COCKPIT_TENANT_DOMAIN=example.ch
COCKPIT_EXTRA_HOST=host01.example.ch
COCKPIT_AGENT_PACKAGE_DIR=$REPO_A/plattform/agentenpakete
COCKPIT_OPS_DIR=$REPO_A/plattform/ops
PLATTFORM_NETZ=magister-plattform
MAGISTER_DIR=$REPO_A
COCKPIT_PLATTFORM_CERTS=$REPO_A/plattform/certs" "$(cat "$DZ/setzen")"
DSN="$(wert COCKPIT_TENANT_ADMIN_DSN "$DZ/startwerte")"
PW="$(sed -n 's|^postgresql+asyncpg://magister:\([^@]*\)@magister-db:5432/magister$|\1|p' <<<"$DSN")"
pruefe "Startwert: DSN zur Datenebene mit neuem Passwort" "64" "$(printf '%s' "$PW" | wc -c)"
pruefe "Startwert: Schemastand aus version.py"   "$KOPF" "$(wert COCKPIT_EXPECTED_SCHEMA_VERSION "$DZ/startwerte")"
pruefe "Startwert: Ablagen der Kundensicherungen" "/var/backups/magister|/var/lib/magister/exports" \
  "$(wert COCKPIT_BACKUP_SHARE_ROOT "$DZ/startwerte")|$(wert COCKPIT_EXPORT_ROOT "$DZ/startwerte")"
if command -v age-keygen >/dev/null; then
  pruefe "Startwert: age-Empfänger der Plattform" "$(cat "$REPO_A/plattform/certs/backup-age.pub")" \
    "$(wert COCKPIT_BACKUP_AGE_RECIPIENT "$DZ/startwerte")"
fi
DATEN_ENV="$REPO_A/deploy/compose/.env"
pruefe "Datenebene: dasselbe Rollenpasswort"     "$PW" "$(wert POSTGRES_PASSWORD "$DATEN_ENV")"
pruefe "Datenebene: Token der Konsole"           "token-der-konsole" "$(wert MAGISTER_CONSOLE_REGISTRY_TOKEN "$DATEN_ENV")"
pruefe "Datenebene: Marker der Konsole"          "marker-der-konsole" "$(wert MAGISTER_CONSOLE_MANAGEMENT_MARKER "$DATEN_ENV")"
pruefe "Plattform-CA bleibt bei Magister, ohne Konsolenzertifikat" "ja|nein" \
  "$(ja_wenn test -f "$REPO_A/plattform/certs/root.pem")|$(ja_wenn test -e "$REPO_A/plattform/certs/console.pem")"
reihenfolge="$(grep -nE 'network create|cockpit.sh up|compose .*deploy/compose .* up -d' "$AUFRUFE" | cut -d: -f1 | paste -sd' ' -)"
erst_netz="$(grep -n 'network create' "$AUFRUFE" | head -1 | cut -d: -f1)"
konsole_up="$(grep -n '^cockpit.sh up' "$AUFRUFE" | head -1 | cut -d: -f1)"
daten_up="$(grep -nE 'deploy/compose/docker-compose.yml.* up -d$' "$AUFRUFE" | head -1 | cut -d: -f1)"
pruefe "Reihenfolge: Netz, Konsole, Datenebene ($reihenfolge)" "ja" \
  "$(ja_wenn test "$erst_netz" -lt "$konsole_up" -a "$konsole_up" -lt "$daten_up")"
pruefe "der Kunde der Konsole angebunden (Token über cockpit.sh wert)" "ja" \
  "$(ja_wenn grep -q '^MAGISTER_TENANT_DSN_TENANT_KUNDE_A=postgresql+asyncpg://r_kunde_a:pw-kunde-a@' "$DATEN_ENV")"
pruefe "Zustand der Konsole über cockpit.sh"     "ja" "$(ja_wenn grep -q '^cockpit.sh status --kurz' "$AUFRUFE")"
pruefe "Operatoren über cockpit.sh"              "ja" "$(ja_wenn grep -q '^cockpit.sh operatoren-zahl' "$AUFRUFE")"
pruefe "kein Compose-Aufruf der Konsole mehr in Magister" "0" \
  "$(grep -c -- "--project-directory $KONSOLE_A" "$AUFRUFE")"

printf '\n\033[1mA2 · Update\033[0m\n'
daten_vorher="$(sha256sum < "$DATEN_ENV")"
: > "$AUFRUFE"
A="$(lauf "$REPO_A" up --ui-neu)"; rc=$?
pruefe "update läuft durch"                      "0" "$rc"
pruefe "--ui-neu reicht weiter"                  "1" "$(grep -c '^cockpit.sh up --ui-neu' "$AUFRUFE")"
pruefe "Startwert-DSN nimmt das Passwort der Datenebene" "$DSN" "$(wert COCKPIT_TENANT_ADMIN_DSN "$DZ/startwerte")"
pruefe "Datenebene unverändert"                  "$daten_vorher" "$(sha256sum < "$DATEN_ENV")"

printf '\n\033[1mA3 · Befehle, die weiterreichen\033[0m\n'
: > "$AUFRUFE"
lauf "$REPO_A" operator --upn person@example.ch --name "Person A" --set-password >/dev/null
pruefe "operator"                                "ja" \
  "$(ja_wenn grep -qx "cockpit.sh operator --upn person@example.ch --name Person A --set-password MAGISTER_DIR=$REPO_A" "$AUFRUFE")"
lauf "$REPO_A" totp --upn person@example.ch --code 123456 >/dev/null
pruefe "totp"                                    "ja" "$(ja_wenn grep -q '^cockpit.sh totp --upn person@example.ch --code 123456' "$AUFRUFE")"
lauf "$REPO_A" down >/dev/null
pruefe "down"                                    "ja" "$(ja_wenn grep -q '^cockpit.sh down ' "$AUFRUFE")"
lauf "$REPO_A" restart >/dev/null
pruefe "restart fragt vorher pruefen"            "ja" \
  "$(ja_wenn test "$(grep -n '^cockpit.sh pruefen' "$AUFRUFE" | tail -1 | cut -d: -f1)" -lt "$(grep -n '^cockpit.sh restart' "$AUFRUFE" | tail -1 | cut -d: -f1)")"
lauf "$REPO_A" purge >/dev/null
pruefe "purge mit --ja"                          "ja" "$(ja_wenn grep -q '^cockpit.sh purge --ja' "$AUFRUFE")"

printf '\n\033[1mA4 · Scheitert der Aufbau der Konsole, startet die Datenebene nicht\033[0m\n'
lauf "$REPO_A" "${ERSTES_UP[@]}" >/dev/null
: > "$AUFRUFE"
UMGEBUNG=(PLATTFORM_KONSOLE="$KONSOLE_A" KONSOLE_UP_SCHEITERT=1)
A="$(lauf "$REPO_A" up)"; rc=$?
pruefe "Abbruch"                                 "1" "$rc"
pruefe "…mit der Meldung der Konsole, nur einer" "ja|nein" \
  "$(ja_wenn grep -q 'Konsole antwortet nicht (Attrappe)' <<<"$A")|$(ja_wenn grep -q 'Abbruch (Code' <<<"$A")"
pruefe "…Datenebene nicht gestartet"             "0" "$(grep -cE 'deploy/compose/docker-compose.yml.* up -d' "$AUFRUFE")"
UMGEBUNG=(PLATTFORM_KONSOLE="$KONSOLE_A")

# =============================================================================
printf '\n\033[1mB · Mit dem echten scripts/cockpit.sh\033[0m\n'
QUELLE="${MAGISTER_TEST_KONSOLE_DIR:-$(dirname "$ECHT")/vitabrevis-cockpit}"
if [ ! -f "$QUELLE/scripts/cockpit.sh" ]; then
  printf '\033[33m  übersprungen: kein Checkout von vitabrevis-cockpit mit scripts/cockpit.sh (%s; MAGISTER_TEST_KONSOLE_DIR)\033[0m\n' "$QUELLE"
else
  REPO_B="$T/b/magister"; KONSOLE_B="$T/b/cockpit"
  neues_repo "$REPO_B"
  mkdir -p "$KONSOLE_B/scripts" "$KONSOLE_B/web/src" "$KONSOLE_B/web/dist"
  cp "$QUELLE/scripts/cockpit.sh" "$KONSOLE_B/scripts/"
  cp -r "$QUELLE/deploy" "$KONSOLE_B/"
  rm -rf "$KONSOLE_B/deploy/.env" "$KONSOLE_B/deploy/certs"
  echo 'export {}' > "$KONSOLE_B/web/src/main.tsx"; touch -d '1 minute ago' "$KONSOLE_B/web/src/main.tsx"
  echo '<html></html>' > "$KONSOLE_B/web/dist/index.html"
  DZ="$T/b/dz"; AUFRUFE="$T/b/aufrufe"
  mkdir -p "$DZ/vol" "$DZ/netz"
  UMGEBUNG=(PLATTFORM_KONSOLE="$KONSOLE_B")
  ENV_K="$KONSOLE_B/deploy/.env"; DATEN_ENV="$REPO_B/deploy/compose/.env"; CERTS="$REPO_B/plattform/certs"
  printf '  Konsole aus %s (%s)\n' "$QUELLE" "$(git -C "$QUELLE" rev-parse --short HEAD 2>/dev/null || echo '?')"

  A="$(lauf "$REPO_B" "${ERSTES_UP[@]}")"; rc=$?
  pruefe "erstes up läuft durch"                 "0" "$rc"
  [ "$rc" -eq 0 ] || printf '%s\n' "$A" | tail -20
  pruefe "die Konsole hat ihre .env angelegt, nur für root" "600" "$(stat -c %a "$ENV_K" 2>/dev/null)"
  pruefe "Rollenpasswort gleich in beiden"       "$(wert COCKPIT_TENANT_ADMIN_DSN "$ENV_K" | sed -n 's|.*://magister:\([^@]*\)@.*|\1|p')" \
    "$(wert POSTGRES_PASSWORD "$DATEN_ENV")"
  pruefe "Bootstrap-Token gleich in beiden"      "$(wert COCKPIT_BOOTSTRAP_TOKEN "$ENV_K")" "$(wert MAGISTER_CONSOLE_REGISTRY_TOKEN "$DATEN_ENV")"
  pruefe "Marker gleich in beiden"               "$(wert COCKPIT_MANAGEMENT_MARKER "$ENV_K")" "$(wert MAGISTER_CONSOLE_MANAGEMENT_MARKER "$DATEN_ENV")"
  pruefe "…und nicht leer"                       "ja" "$(ja_wenn test -n "$(wert COCKPIT_MANAGEMENT_MARKER "$ENV_K")")"
  pruefe "Orte in der .env der Konsole"          "$REPO_B|$CERTS|magister-plattform" \
    "$(wert MAGISTER_DIR "$ENV_K")|$(wert COCKPIT_PLATTFORM_CERTS "$ENV_K")|$(wert PLATTFORM_NETZ "$ENV_K")"
  pruefe "Zertifikat der Konsole aus der Plattform-CA, mit allen Namen" \
    "DNS:konsole.example.ch,DNS:localhost,IPAddress:127.0.0.1,DNS:host01.example.ch" \
    "$(openssl x509 -in "$CERTS/console.pem" -noout -ext subjectAltName 2>/dev/null | tail -n +2 | tr -d ' ')"
  pruefe "…von der Wurzel ausgestellt"           "OK" "$(openssl verify -CAfile "$CERTS/root.pem" "$CERTS/console.pem" 2>&1 | sed 's/.*: //')"
  pruefe "zehn Dateien in deploy/certs der Konsole" "10" "$(find "$KONSOLE_B/deploy/certs" -type f | wc -l)"
  pruefe "Compose der Konsole: mit Überlagerung, Magister aus diesem Repo" "ja" \
    "$(ja_wenn grep -qF "MAGISTER_DIR=$REPO_B docker compose --project-directory $KONSOLE_B/deploy -f $KONSOLE_B/deploy/docker-compose.yml -f $KONSOLE_B/deploy/docker-compose.plattform.yml up -d --build" "$AUFRUFE")"
  pruefe "Migration der Konsole"                 "ja" "$(ja_wenn grep -q 'exec -T api alembic upgrade head' "$AUFRUFE")"

  printf '\n\033[1mB2 · Update: nichts neu erzeugen\033[0m\n'
  konsole_vorher="$(sha256sum < "$ENV_K")"; daten_vorher="$(sha256sum < "$DATEN_ENV")"
  cert_vorher="$(sha256sum < "$CERTS/console.pem")"; ca_vorher="$(sha256sum < "$CERTS/root.pem")"
  A="$(lauf "$REPO_B" up)"; rc=$?
  pruefe "update läuft durch"                    "0" "$rc"
  pruefe ".env der Konsole unverändert"          "$konsole_vorher" "$(sha256sum < "$ENV_K")"
  pruefe ".env der Datenebene unverändert"       "$daten_vorher" "$(sha256sum < "$DATEN_ENV")"
  pruefe "Zertifikat der Konsole unverändert"    "$cert_vorher" "$(sha256sum < "$CERTS/console.pem")"
  pruefe "Plattform-CA unverändert"              "$ca_vorher" "$(sha256sum < "$CERTS/root.pem")"

  printf '\n\033[1mB3 · Dev-Host: Konsole und Datenebene, wie Magister sie bisher anlegte\033[0m\n'
  # Die .env der Konsole im Format von plattform-aufbau.sh vor dem Umbau, mit
  # den Geheimnissen, die zur Datenebene passen – und ohne die Orte.
  cat > "$ENV_K" <<EOF
# --- erzeugt von plattform-aufbau.sh ---
COCKPIT_BIND_ADDRESS=127.0.0.1
COCKPIT_HOSTNAME=konsole.example.ch
COCKPIT_CONNECTOR_HOSTNAME=connect.example.ch
# Unter dieser Domäne liegen die Kunden (<kunde>.<domäne>). Die Konsole
# weist beim Anlegen jeden anderen Hostnamen ab — und die zwei Namen oben.
COCKPIT_TENANT_DOMAIN=example.ch
COCKPIT_EXTRA_HOST=host01.example.ch
COCKPIT_BOOTSTRAP_TOKEN=$(wert MAGISTER_CONSOLE_REGISTRY_TOKEN "$DATEN_ENV")
COCKPIT_SECRET_KEY=Ab/cd+EF==
COCKPIT_MANAGEMENT_MARKER=$(wert MAGISTER_CONSOLE_MANAGEMENT_MARKER "$DATEN_ENV")
COCKPIT_CONNECTOR_MARKER=anderer-marker
COCKPIT_TENANT_ADMIN_DSN=postgresql+asyncpg://magister:$(wert POSTGRES_PASSWORD "$DATEN_ENV")@magister-db:5432/magister
COCKPIT_TENANT_EXTENSION_SCHEMA=public
COCKPIT_EXPECTED_SCHEMA_VERSION=0049_alt
COCKPIT_BACKUP_SHARE_ROOT=/var/backups/magister
COCKPIT_EXPORT_ROOT=/var/lib/magister/exports
COCKPIT_BACKUP_AGE_RECIPIENT=
COCKPIT_AGENT_PACKAGE_DIR=$REPO_B/plattform/agentenpakete
COCKPIT_OPS_DIR=$REPO_B/plattform/ops
PLATTFORM_NETZ=magister-plattform
EOF
  chmod 600 "$ENV_K"
  alt="$(cat "$ENV_K")"
  daten_vorher="$(sha256sum < "$DATEN_ENV")"
  : > "$AUFRUFE"
  A="$(lauf "$REPO_B" up)"; rc=$?
  pruefe "cd /opt/magister && plattform-aufbau.sh up läuft durch" "0" "$rc"
  pruefe "alle Zeilen der bisherigen .env unverändert" "$alt" "$(head -n "$(wc -l <<<"$alt")" "$ENV_K")"
  pruefe "nur die Orte angehängt"                "MAGISTER_DIR=$REPO_B
COCKPIT_PLATTFORM_CERTS=$CERTS" "$(tail -n +"$(( $(wc -l <<<"$alt") + 1 ))" "$ENV_K")"
  pruefe "Rechte bleiben"                        "600" "$(stat -c %a "$ENV_K")"
  pruefe ".env der Datenebene unverändert"       "$daten_vorher" "$(sha256sum < "$DATEN_ENV")"
  pruefe "Zertifikat der Konsole unverändert"    "$cert_vorher" "$(sha256sum < "$CERTS/console.pem")"
  pruefe "danach allein aus dem Cockpit-Repo: update" "ja" \
    "$(ja_wenn bash -c "env PATH='$T/bin:$PATH' AUFRUFE='$AUFRUFE' DZ='$DZ' bash '$KONSOLE_B/scripts/cockpit.sh' update 2>&1 | grep -q 'Konsole antwortet'")"
  pruefe "…ohne die .env zu ändern"              "ja" "$(ja_wenn test "$(head -n "$(wc -l <<<"$alt")" "$ENV_K")" = "$alt")"

  printf '\n\033[1mB4 · Datenbank der Konsole da, .env weg: Magister legt nichts an\033[0m\n'
  mv "$ENV_K" "$T/b/env.weg"
  : > "$AUFRUFE"
  A="$(lauf "$REPO_B" up)"; rc=$?
  pruefe "Abbruch"                               "1" "$rc"
  pruefe "…mit dem Grund aus der Konsole"        "ja" "$(ja_wenn grep -q 'ihre Umgebung fehlt' <<<"$A")"
  pruefe "…keine neue .env"                      "nein" "$(ja_wenn test -e "$ENV_K")"
  pruefe "…nichts gestartet"                     "0" "$(grep -c ' up -d' "$AUFRUFE")"
  mv "$T/b/env.weg" "$ENV_K"
fi

printf '\n'
if [ "$ROT" -eq 0 ]; then
  printf '\033[32m%d bestanden, 0 gescheitert\033[0m\n' "$GRUEN"
  exit 0
fi
printf '\033[31m%d bestanden, %d gescheitert\033[0m\n' "$GRUEN" "$ROT"
exit 1
