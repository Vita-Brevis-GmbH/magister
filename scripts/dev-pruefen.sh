#!/usr/bin/env bash
# Die Zusagen der Mandantenfähigkeit gegen die laufende Entwicklungsumgebung
# prüfen — nicht gegen Testdoubles, sondern gegen Postgres, die Konsole, die
# Datenebene und Caddy.
#
#   ./scripts/dev-pruefen.sh          # alle Prüfungen
#   ./scripts/dev-pruefen.sh T3 T7    # nur diese
#
# Voraussetzung: `scripts/dev-umgebung.sh up` ist gelaufen und die Dienste
# laufen (`status` zeigt drei Mal „läuft").
#
# **Was diese Datei von den Unit-Tests unterscheidet:** dort ist alles
# injiziert — hier ist nichts injiziert. Eine Prüfung, die hier scheitert,
# scheitert an der echten Verdrahtung: an einer Rolle, einem `search_path`,
# einem Header, einem Zertifikat. Genau die Fehler, die in dieser Codebasis
# gefunden wurden, waren von dieser Art.
#
# Jede Prüfung nennt die **Zusage**, dann das Ergebnis. Wo es geht, wird der
# negative Fall geprüft: dass etwas NICHT geht, ist die eigentliche Aussage.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV="${DEV_ROOT:-$REPO/dev}"
CERTS="$DEV/certs"
API_PORT="${DEV_API_PORT:-8000}"
CONSOLE_PORT="${DEV_CONSOLE_PORT:-8099}"
CONSOLE_TLS_PORT="${DEV_CONSOLE_TLS_PORT:-4444}"
CONSOLE_HOST="${DEV_CONSOLE_HOST:-console.mgmt.vitabrevis.dev}"

[ -f "$DEV/env.console" ] || { echo "Keine Umgebung in $DEV — erst 'dev-umgebung.sh up'."; exit 2; }
# shellcheck disable=SC1091
source "$DEV/env.console"
# shellcheck disable=SC1091
source "$DEV/env.dataplane"

PASS=0; FAIL=0; SKIP=0
CURRENT=""

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }
skip() { printf '  \033[33m–\033[0m %s\n' "$*"; SKIP=$((SKIP+1)); }
head2(){ CURRENT="$1"; printf '\n\033[1m%s · %s\033[0m\n' "$1" "$2"; }

wanted() {  # Läuft diese Prüfung?
  [ $# -eq 0 ] && return 0
  for want in "$@"; do [ "$want" = "$CURRENT" ] && return 0; done
  return 1
}

# psql gegen die Kundenrolle: der Treiber im DSN muss weg, den kennt nur
# SQLAlchemy.
pg() { psql "${1/+asyncpg/}" -qtAX "${@:2}"; }
admin_dsn() { echo "${COCKPIT_TENANT_ADMIN_DSN/+asyncpg/}"; }
console_dsn() { echo "${COCKPIT_DATABASE_URL/+asyncpg/}"; }

console_api() {  # $1 Methode, $2 Pfad, $3 Rumpf
  local args=(-sS -o /dev/stdout -w "\n%{http_code}" -X "$1" "http://127.0.0.1:$CONSOLE_PORT$2"
    -H "Authorization: Bearer $COCKPIT_BOOTSTRAP_TOKEN"
    -H "X-Magister-Management: $COCKPIT_MANAGEMENT_MARKER")
  [ $# -ge 3 ] && args+=(-H "Content-Type: application/json" -d "$3")
  curl "${args[@]}" 2>/dev/null
}

probe() {  # Tiefe Sonde für einen Kunden; $1 = Slug
  curl -sS -H "X-Magister-Health: $MAGISTER_HEALTH_TOKEN" \
    -H "Host: $1.mgmt.vitabrevis.dev" \
    "http://127.0.0.1:$API_PORT/healthz/stack" 2>/dev/null
}

json_get() { python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get(sys.argv[2], ""))' "$1" "$2" 2>/dev/null; }

check_named() {  # $1 = JSON der Sonde, $2 = Prüfungsname -> "status detail"
  python3 - "$1" "$2" <<'PY' 2>/dev/null
import json, sys
data = json.loads(sys.argv[1])
for c in data.get("checks", []):
    if c["name"] == sys.argv[2]:
        print(c["status"], c["detail"])
        break
PY
}

# --- T1 ----------------------------------------------------------------------
t1() {
  head2 T1 "Die Trennung hält — an Postgres, nicht an Anwendungslogik (ADR-0013 D1)"
  wanted "$@" || return 0
  local thun="$MAGISTER_TENANT_DSN_TENANT_THUN"
  local rows
  rows="$(pg "$thun" -c "select count(*) from t_thun.classes" 2>&1)"
  [[ "$rows" =~ ^[0-9]+$ ]] && ok "r_thun liest sein eigenes Schema ($rows Klassen)" \
    || bad "r_thun kommt nicht an sein eigenes Schema: $rows"

  local fremd
  fremd="$(pg "$thun" -c "select count(*) from t_bern.classes" 2>&1)"
  if echo "$fremd" | grep -qi "permission denied\|keine Berechtigung"; then
    ok "r_thun kommt NICHT in das Schema von bern (Postgres verweigert)"
  else
    bad "r_thun konnte t_bern lesen — die Trennung greift nicht: $fremd"
  fi

  # Und die Umkehr, damit nicht eine einseitige Vergabe als Trennung durchgeht.
  local rueck
  rueck="$(pg "$MAGISTER_TENANT_DSN_TENANT_BERN" -c "select count(*) from t_thun.classes" 2>&1)"
  echo "$rueck" | grep -qi "permission denied\|keine Berechtigung" \
    && ok "und r_bern nicht in das Schema von thun" \
    || bad "r_bern konnte t_thun lesen: $rueck"
}

# --- T2 ----------------------------------------------------------------------
t2() {
  head2 T2 "Jeder Hostname landet bei seinem Kunden (ADR-0013 D3)"
  wanted "$@" || return 0
  for slug in thun bern; do
    local got; got="$(json_get "$(probe "$slug")" tenant)"
    [ "$got" = "$slug" ] && ok "$slug.mgmt… wird als '$slug' aufgelöst" \
      || bad "$slug.mgmt… wurde als '${got:-nichts}' aufgelöst"
  done
  local unknown; unknown="$(curl -sS -H "X-Magister-Health: $MAGISTER_HEALTH_TOKEN" \
    -H "Host: fremd.example.invalid" "http://127.0.0.1:$API_PORT/healthz/stack" 2>/dev/null)"
  [ "$(json_get "$unknown" status)" = "2" ] \
    && ok "ein unbekannter Hostname ist ein kritischer Befund, kein Kunde" \
    || bad "unbekannter Hostname: $(echo "$unknown" | head -c 120)"
}

# --- T3 ----------------------------------------------------------------------
t3() {
  head2 T3 "Die Versions-Schranke hält einen Kunden zurück (ADR-0013 D7)"
  wanted "$@" || return 0
  local echt
  echt="$(pg "$(console_dsn)" -c "select schema_version from tenants where slug='thun'")"
  pg "$(console_dsn)" -c "update tenants set schema_version='0001_veraltet' where slug='thun'" >/dev/null
  # Die Datenebene lädt die Registry im Hintergrund nach.
  local waited=0 answer=""
  while [ "$waited" -lt 150 ]; do
    # `/auth/capabilities`: öffentlich, ohne Anmeldung, und trotzdem hinter
    # der Mandanten-Middleware. `/api/me` gibt es auf diesem Port nicht — den
    # Präfix streift erst Caddy ab, und ein 404 sähe hier aus wie „keine
    # Wartung". Beim ersten Lauf genau so danebengegriffen.
    answer="$(curl -sS -o /dev/null -w "%{http_code}" -H "Host: thun.mgmt.vitabrevis.dev" \
      "http://127.0.0.1:$API_PORT/auth/capabilities" 2>/dev/null)"
    [ "$answer" = "503" ] && break
    # `dev-umgebung.sh` stellt den Takt auf 30 s (kleinster erlaubter Wert;
    # in Produktion sind es 300 s). Wer die Datenebene von Hand startet, muss
    # entsprechend länger warten — daher das grosszügige Budget.
    sleep 5; waited=$((waited+5))
  done
  [ "$answer" = "503" ] && ok "die Kundenseite antwortet mit 503 (nach ${waited}s)" \
    || bad "die Kundenseite antwortet mit $answer statt 503"

  local schema; schema="$(check_named "$(probe thun)" schema_version)"
  echo "$schema" | grep -q "^2 " && ok "die Sonde sagt WARUM: ${schema#2 }" \
    || bad "die Sonde meldet keinen kritischen Schemastand: $schema"

  pg "$(console_dsn)" -c "update tenants set schema_version='$echt' where slug='thun'" >/dev/null
  ok "zurückgesetzt auf $echt"
}

# --- T4 ----------------------------------------------------------------------
t4() {
  head2 T4 "Jeder Kunde hat seinen eigenen Schlüssel (ADR-0016 D8)"
  wanted "$@" || return 0
  local a="$MAGISTER_TENANT_AUDIT_KEY_THUN" b="$MAGISTER_TENANT_AUDIT_KEY_BERN"
  [ -n "$a" ] && [ -n "$b" ] && [ "$a" != "$b" ] \
    && ok "zwei verschiedene Kundenschlüssel hinterlegt" \
    || bad "die Kundenschlüssel fehlen oder sind gleich"
  for slug in thun bern; do
    local k; k="$(check_named "$(probe "$slug")" tenant_key)"
    echo "$k" | grep -q "^0 " && ok "$slug: Schlüssel vorhanden" || bad "$slug: $k"
  done
}

# --- T5 ----------------------------------------------------------------------
t5() {
  head2 T5 "Audit-Inhalte liegen verschlüsselt in der Datenbank (ADR-0016 D2)"
  wanted "$@" || return 0
  local dsn="$MAGISTER_TENANT_DSN_TENANT_THUN"
  local n
  n="$(pg "$dsn" -c "select count(*) from t_thun.audit_events")"
  if [ "${n:-0}" = "0" ]; then
    skip "noch kein Audit-Ereignis bei thun — erst T7 laufen lassen"
    return 0
  fi

  # 1. Wer die Spalte roh liest, sieht nichts. Nicht „sieht keine geschweifte
  #    Klammer" — Zufallsbytes enthalten welche. Gesucht wird die Zeichenfolge,
  #    die in JEDEM Klartext steht: der Schlüsselname "action".
  local leaks
  leaks="$(pg "$dsn" -c \
    "select count(*) from t_thun.audit_events where encode(payload,'escape') like '%action%'")"
  if [ "${leaks:-1}" != "0" ]; then
    bad "$leaks von $n Payloads sind im Klartext lesbar"
  else
    ok "keiner von $n Payloads ist roh lesbar"
  fi

  # 2. Die Gegenprobe — sonst prüfte Schritt 1 auch eine kaputte Spalte ab.
  #    Mit dem Schlüssel DIESES Kunden kommt JSON zurück.
  local clear
  # Über die Standardeingabe, nicht über -c: psql ersetzt seine Variablen nur
  # dort. Der Schlüssel steht damit nicht in der Prozessliste.
  clear="$(pg "$dsn" -v "k=$MAGISTER_TENANT_AUDIT_KEY_THUN" \
    <<<"select pgp_sym_decrypt(payload, :'k') from t_thun.audit_events order by id limit 1" 2>&1)"
  if echo "$clear" | python3 -c 'import json,sys; json.loads(sys.stdin.read())' 2>/dev/null; then
    ok "mit dem Schlüssel von thun wird daraus wieder JSON"
  else
    bad "Entschlüsseln mit dem Kundenschlüssel scheitert: $(echo "$clear" | head -c 80)"
  fi

  # 3. Und mit dem Schlüssel des ANDEREN Kunden nicht. Das ist die eigentliche
  #    Aussage: ein Kundenschlüssel öffnet genau ein Archiv.
  local foreign
  foreign="$(pg "$dsn" -v "k=$MAGISTER_TENANT_AUDIT_KEY_BERN" \
    <<<"select pgp_sym_decrypt(payload, :'k') from t_thun.audit_events order by id limit 1" 2>&1)"
  if echo "$foreign" | grep -qi 'wrong key or corrupt data'; then
    ok "der Schlüssel von bern öffnet das Archiv von thun nicht"
  else
    bad "der Schlüssel von bern entschlüsselt Audit-Daten von thun: $(echo "$foreign" | head -c 60)"
  fi
}

# --- T6 ----------------------------------------------------------------------
t6() {
  head2 T6 "Lastgrenzen gelten in Postgres, nicht nur in der Konsole (ADR-0021 D3)"
  wanted "$@" || return 0
  local id
  id="$(console_api GET "/api/tenants" | python3 -c '
import json,sys
body = sys.stdin.read().rsplit("\n",1)[0]
print(next(t["id"] for t in json.loads(body) if t["slug"]=="thun"))' 2>/dev/null)"
  [ -z "$id" ] && { bad "Kunde thun nicht in der Konsole gefunden"; return 0; }

  local resp code
  resp="$(console_api PUT "/api/tenants/$id/limits" \
    '{"statement_timeout_ms":17000,"idle_in_transaction_ms":45000,"connection_limit":55,"reason":"Pruefung dev-pruefen.sh"}')"
  code="$(echo "$resp" | tail -1)"
  if [ "$code" = "403" ]; then
    skip "Grenzen setzen verlangt eine Person (Bootstrap-Token reicht nicht) — in der Oberfläche prüfen"
    return 0
  fi
  [ "$code" = "200" ] && ok "die Konsole nimmt die Änderung an" || { bad "HTTP $code"; return 0; }

  local conf
  conf="$(pg "$(admin_dsn)" -c "select rolconnlimit || ' ' || coalesce(array_to_string(rolconfig,','),'') from pg_roles where rolname='r_thun'")"
  echo "$conf" | grep -q "^55 " && ok "CONNECTION LIMIT 55 steht an der Rolle" || bad "rolconnlimit: $conf"
  echo "$conf" | grep -q "statement_timeout=17000ms" && ok "statement_timeout 17000ms steht an der Rolle" \
    || bad "rolconfig: $conf"
}

# --- T7 ----------------------------------------------------------------------
t7() {
  head2 T7 "Migrationswelle: verschlüsselter Dump, Halt beim Kanarienvogel (ADR-0021 D1/D2)"
  wanted "$@" || return 0
  command -v age >/dev/null || { skip "age fehlt"; return 0; }
  [ -z "${MAGISTER_BACKUP_AGE_RECIPIENT:-}" ] && { skip "kein age-Empfänger hinterlegt"; return 0; }
  mkdir -p "$DEV/dumps"

  local out
  out="$(cd "$REPO/apps/api" && uv run ../../scripts/magister-cli tenants migrate \
    --canary thun --canary-only --dump-dir "$DEV/dumps" 2>&1)"
  echo "$out" | grep -q "canary-only: hier ist Schluss" \
    && ok "die Welle hält nach dem Kanarienvogel an" \
    || bad "kein Halt nach dem Kanarienvogel: $(echo "$out" | tail -2 | head -1)"
  echo "$out" | grep -q "Protokoll ok, gemeldet" \
    && ok "Audit geschrieben und Stand an die Konsole gemeldet" \
    || bad "Rollout-Ereignis oder Meldung fehlt"

  local dump
  dump="$(ls -t "$DEV/dumps"/thun-*.dump.age 2>/dev/null | head -1)"
  [ -z "$dump" ] && { bad "kein Dump entstanden"; return 0; }
  head -c 21 "$dump" | grep -q "age-encryption.org" \
    && ok "der Dump ist verschlüsselt ($(stat -c%s "$dump") Bytes)" \
    || bad "der Dump beginnt nicht mit einem age-Kopf"
  # In eine Datei und nicht in eine Pipe: `head -c 16` schliesst die Pipe,
  # `age` bekommt SIGPIPE, und mit `pipefail` scheiterte die Prüfung an einem
  # Dump, der tadellos entschlüsselbar war.
  local klar="$DEV/dumps/.pruefung.sql"
  if age -d -i "$CERTS/backup-age.key" "$dump" > "$klar" 2>/dev/null \
     && [ "$(head -c 5 "$klar")" = "PGDMP" ]; then
    ok "und mit dem Dev-Schlüssel entschlüsselbar ($(stat -c%s "$klar") Bytes, pg_dump-Format)"
  else
    bad "der Dump lässt sich mit dem hinterlegten Schlüssel nicht lesen"
  fi
  rm -f "$klar"

  # Der negative Fall, der die harte Regel trägt.
  local ohne
  ohne="$(cd "$REPO/apps/api" && MAGISTER_BACKUP_AGE_RECIPIENT= \
    uv run ../../scripts/magister-cli tenants migrate --canary-only --dump-dir "$DEV/dumps" 2>&1)"
  echo "$ohne" | grep -qi "empfänger\|recipient" \
    && ok "ohne Empfänger läuft die Welle GAR NICHT an" \
    || bad "die Welle lief ohne age-Empfänger an"
}

# --- T8 ----------------------------------------------------------------------
t8() {
  head2 T8 "Die Konsole erfährt den echten Schemastand (ADR-0021 D2)"
  wanted "$@" || return 0
  local row
  row="$(pg "$(console_dsn)" -c "select schema_version, schema_version_reported_at is not null from tenants where slug='thun'")"
  echo "$row" | grep -q "|t$" && ok "thun: Stand gemeldet ($(echo "$row" | cut -d'|' -f1))" \
    || bad "thun: kein gemeldeter Stand — erst T7 laufen lassen ($row)"
}

# --- T9 ----------------------------------------------------------------------
t9() {
  head2 T9 "Die Sonden für die Überwachung (ADR-0021 D6)"
  wanted "$@" || return 0
  local code
  code="$(curl -sS -o /dev/null -w "%{http_code}" \
    -H "Host: thun.mgmt.vitabrevis.dev" "http://127.0.0.1:$API_PORT/healthz/stack" 2>/dev/null)"
  [ "$code" = "404" ] && ok "ohne Token gibt es die Sonde nicht (404)" || bad "ohne Token: HTTP $code"

  code="$(curl -sS -o /dev/null -w "%{http_code}" -H "X-Magister-Health: falsch" \
    -H "Host: thun.mgmt.vitabrevis.dev" "http://127.0.0.1:$API_PORT/healthz/stack" 2>/dev/null)"
  [ "$code" = "404" ] && ok "mit falschem Token sieht es genauso aus" || bad "falscher Token: HTTP $code"

  local body; body="$(probe thun)"
  [ -n "$(json_get "$body" status)" ] && ok "mit Token: Stufe $(json_get "$body" status) ($(json_get "$body" state))" \
    || bad "keine verwertbare Antwort"

  local konsole
  konsole="$(curl -sS "http://127.0.0.1:$CONSOLE_PORT/api/health/stack" \
    -H "X-Magister-Management: $COCKPIT_MANAGEMENT_MARKER" 2>/dev/null)"
  [ -n "$(json_get "$konsole" status)" ] \
    && ok "die Konsole meldet Stufe $(json_get "$konsole" status)" \
    || bad "die Konsolen-Sonde antwortet nicht: $(echo "$konsole" | head -c 80)"

  local exitcode
  (cd "$REPO/cockpit/api" && uv run python -m cockpit_api.cli.fleet_check >/dev/null 2>&1); exitcode=$?
  [ "$exitcode" -le 2 ] && ok "fleet_check liefert Exit-Code $exitcode (0/1/2 wie erwartet)" \
    || bad "fleet_check: Exit $exitcode"
}

# --- T10 ---------------------------------------------------------------------
t10() {
  head2 T10 "Die Konsole hält keine Zugangsdaten (ADR-0013 D4)"
  wanted "$@" || return 0
  local hits
  hits="$(pg "$(console_dsn)" -c "select count(*) from tenants where dsn_ref like '%://%' or dsn_ref like '%:%@%'")"
  [ "$hits" = "0" ] && ok "in der Registry stehen Verweise, keine DSNs" || bad "$hits Zeilen sehen wie DSNs aus"

  local body ref
  body="$(curl -sS "http://127.0.0.1:$CONSOLE_PORT/api/tenants/registry" \
    -H "Authorization: Bearer $COCKPIT_BOOTSTRAP_TOKEN" \
    -H "X-Magister-Management: $COCKPIT_MANAGEMENT_MARKER" 2>/dev/null)"
  echo "$body" | grep -q "password\|postgresql://" \
    && bad "die Registry-Antwort enthält Zugangsdaten" \
    || ok "auch die Registry-Antwort enthält keine"
  ref="$(echo "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["dsn_ref"])' 2>/dev/null)"
  [ -n "$ref" ] && ok "Beispiel-Verweis: $ref" || skip "Registry leer"
}

# --- T11 ---------------------------------------------------------------------
t11() {
  head2 T11 "Der Umzug verlangt einen gesperrten Kunden (ADR-0021 D5)"
  wanted "$@" || return 0
  local id
  id="$(console_api GET "/api/tenants" | python3 -c '
import json,sys
body = sys.stdin.read().rsplit("\n",1)[0]
print(next(t["id"] for t in json.loads(body) if t["slug"]=="bern"))' 2>/dev/null)"
  [ -z "$id" ] && { bad "Kunde bern nicht gefunden"; return 0; }

  local code
  code="$(console_api POST "/api/tenants/$id/relocate" \
    '{"dsn_ref":"tenant_bern_c2","isolation_mode":"cluster","reason":"Pruefung dev-pruefen"}' | tail -1)"
  if [ "$code" = "403" ]; then
    skip "Umzug verlangt eine Person — in der Oberfläche prüfen"
    return 0
  fi
  [ "$code" = "409" ] && ok "bei aktivem Kunden abgelehnt (409)" || bad "aktiver Kunde: HTTP $code statt 409"

  console_api POST "/api/tenants/$id/suspend" '{"reason":"Pruefung dev-pruefen"}' >/dev/null
  code="$(console_api POST "/api/tenants/$id/relocate" \
    '{"dsn_ref":"tenant_bern_c2","isolation_mode":"cluster","reason":"Pruefung dev-pruefen"}' | tail -1)"
  [ "$code" = "200" ] && ok "bei gesperrtem Kunden angenommen" || bad "gesperrter Kunde: HTTP $code"

  local nach
  nach="$(pg "$(console_dsn)" -c "select dsn_ref || ' ' || isolation_mode || ' ' || coalesce(schema_version,'-') from tenants where slug='bern'")"
  echo "$nach" | grep -q "tenant_bern_c2 cluster" && ok "Verweis und Trennung umgestellt: $nach" || bad "$nach"

  # Zurück in den Ausgangszustand, sonst ist die Umgebung nach der Prüfung kaputt.
  pg "$(console_dsn)" -c "update tenants set dsn_ref='tenant_bern', isolation_mode='schema', schema_version='$(pg "$(console_dsn)" -c "select schema_version from tenants where slug='thun'")' where slug='bern'" >/dev/null
  console_api POST "/api/tenants/$id/unsuspend" >/dev/null
  ok "zurückgesetzt (bern wieder aktiv, Verweis tenant_bern)"
}

# --- T12 ---------------------------------------------------------------------
t12() {
  head2 T12 "Die Konsole ist ohne Client-Zertifikat nicht erreichbar (ADR-0020 D1)"
  wanted "$@" || return 0
  command -v caddy >/dev/null || { skip "caddy fehlt — kein TLS-Listener"; return 0; }
  local code
  # Über den NAMEN und nicht über die IP: ohne SNI weiss Caddy nicht, welches
  # Zertifikat gilt, und antwortet mit 421 — was hier wie ein kaputter
  # Listener aussähe. `--resolve` spart den Eintrag in /etc/hosts.
  local resolve=(--resolve "$CONSOLE_HOST:$CONSOLE_TLS_PORT:127.0.0.1")
  code="$(curl -sk --noproxy '*' "${resolve[@]}" -o /dev/null -w "%{http_code}" \
    "https://$CONSOLE_HOST:$CONSOLE_TLS_PORT/api/auth/console/whoami" 2>/dev/null)"
  [ "$code" = "000" ] && ok "ohne Zertifikat scheitert schon der Handshake" \
    || bad "ohne Zertifikat kam HTTP $code — der Listener verlangt keines"

  local body
  body="$(curl -sk --noproxy '*' "${resolve[@]}" \
    --cert "$CERTS/operator.pem" --key "$CERTS/operator-key.pem" \
    "https://$CONSOLE_HOST:$CONSOLE_TLS_PORT/api/auth/console/whoami" 2>/dev/null)"
  local stage; stage="$(json_get "$body" stage)"
  case "$stage" in
    unknown_certificate) ok "Zertifikat erkannt, aber kein Operator eingetragen (erwartet vor add_operator)" ;;
    enrolment_required)  ok "Operator erkannt, zweiter Faktor noch einzurichten" ;;
    totp_required)       ok "Operator erkannt, zweiter Faktor verlangt" ;;
    *) bad "unerwartete Antwort: $(echo "$body" | head -c 100)" ;;
  esac
}

# T5 läuft NACH T7, nicht an fünfter Stelle: die Audit-Ereignisse, an denen
# es die Verschlüsselung prüft, entstehen in der Migrationswelle von T7. Auf
# einer frisch aufgebauten Umgebung gibt es vorher keines — T5 übersprang
# sich dann selbst, und ein übersprungener Test beweist nichts.
for t in t1 t2 t3 t4 t6 t7 t5 t8 t9 t10 t11 t12; do "$t" "$@"; done

printf '\n\033[1m%d bestanden, %d gescheitert, %d übersprungen\033[0m\n' "$PASS" "$FAIL" "$SKIP"
[ "$FAIL" -eq 0 ] || exit 1
