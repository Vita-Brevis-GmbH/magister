#!/usr/bin/env bash
# scripts/betrieb.sh — der Einstiegspunkt für den Host-Agenten des Cockpits
# (Vertrag betrieb/v1, ADR-0028).
#
# Mit echtem git (ein Ursprung, ein Checkout in Temp-Verzeichnissen), echtem
# age und echtem flock; Attrappen für docker (Datenebene, pg-backup, Postgres)
# und für plattform-aufbau.sh. Die „Datenbank" ist eine Datei mit ihrem
# Schemastand; die Attrappe von plattform-aufbau.sh migriert sie auf den Stand
# des Checkouts und scheitert wie Alembic, wenn die Datenbank neuer ist als
# der Code.
#
# Geprüft wird, was das Cockpit sich darauf verlässt:
#   * stdout ist genau eine Zeile JSON nach betrieb/v1 — bei jedem Ausgang;
#   * ungültige oder unbekannte Ref, lokale Änderungen, ältere Version,
#     gescheiterte Sicherung → Exit 3, nichts geändert (kein Umschalten, kein
#     Aufbau, keine Sicherung);
#   * gleiche Version → Exit 0 „schon auf";
#   * Health scheitert → selbst zurück (Code und Datenbank), Exit 1;
#   * ohne privaten Schlüssel: nur der Code zurück, wenn der Schemastand gleich
#     ist (Exit 1), sonst Exit 2 mit dem nächsten Schritt;
#   * `zurueck` genau einmal; Sperre belegt → Exit 4;
#   * Repo privat: `--bundle <datei> --commit <sha>` holt den Stand aus dem
#     git-Bundle und kontaktiert origin nie (origin zeigt auf eine ungültige
#     Adresse mit einer Falle als upload-pack); Bundle defekt bzw. ohne den
#     Commit → Exit 3; Branch ohne Upstream, sonst losgelöst; docker erbt
#     DOCKER_CONFIG, die Antwort nennt es nie.
#
#   ./scripts/tests/betrieb.test.sh
set -uo pipefail

ECHT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
T="$(mktemp -d)"
HALTER=""
aufraeumen() {
  [ -z "$HALTER" ] || kill "$HALTER" 2>/dev/null || true
  rm -rf "$T"
}
trap aufraeumen EXIT

for w in git age age-keygen flock timeout python3 sha256sum; do
  command -v "$w" >/dev/null || { echo "betrieb.test.sh: $w fehlt" >&2; exit 1; }
done

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
enthaelt() { case "$2" in *"$1"*) echo ja ;; *) echo nein ;; esac; }

G=(git -c user.name=Test -c user.email=test@example.ch -c init.defaultBranch=main
   -c advice.detachedHead=false)

# --- Ursprung und Stände ---------------------------------------------------------
#   A  v1.0.0 (main)          Schemastand public=0001
#   B  main                   Schemastand public=0001
#   C  kaputt-migration       public=0002, Health scheitert
#   D  kaputt-gleich          public=0001, Health scheitert
#   E  aufbau-kaputt          plattform-aufbau.sh update scheitert
DZ="$T/dz"
mkdir -p "$T/bin" "$T/home" "$DZ/sicherungen"
"${G[@]}" init -q --bare "$T/origin.git"
"${G[@]}" clone -q "$T/origin.git" "$T/arbeit" 2>/dev/null
A_W="$T/arbeit"
mkdir -p "$A_W/scripts" "$A_W/deploy/compose"
cp "$ECHT/.gitignore" "$A_W/.gitignore"
cp "$ECHT/scripts/betrieb.sh" "$A_W/scripts/betrieb.sh"
chmod 755 "$A_W/scripts/betrieb.sh"
cat >"$A_W/scripts/plattform-aufbau.sh" <<'X'
#!/usr/bin/env bash
# Attrappe: schreibt mit und migriert die „Datenbank" auf den Stand des Codes.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "aufbau-ausgabe auf stdout"
echo "$* $(git -c safe.directory="$REPO" -C "$REPO" rev-parse HEAD) fragen=${PLATTFORM_NICHT_FRAGEN:-ja}" >>"$DZ/aufbau"
[ -f "$REPO/deploy/compose/aufbau-kaputt" ] && exit 1
code="$(cat "$REPO/deploy/compose/schema")"
db="$(cat "$DZ/db" 2>/dev/null)" || { echo "keine Datenbank" >&2; exit 1; }
if [[ "${db##*=}" > "${code##*=}" ]]; then echo "Can't locate revision" >&2; exit 1; fi
printf '%s' "$code" >"$DZ/db"
X
chmod 755 "$A_W/scripts/plattform-aufbau.sh"
printf 'services: {}\n' >"$A_W/deploy/compose/docker-compose.yml"
printf 'services: {}\n' >"$A_W/deploy/compose/docker-compose.plattform.yml"
printf 'public=0001' >"$A_W/deploy/compose/schema"
echo a >"$A_W/VERSION"
commit() { "${G[@]}" -C "$A_W" add -A && "${G[@]}" -C "$A_W" commit -q -m "$1"; }
commit "A"
"${G[@]}" -C "$A_W" tag v1.0.0
"${G[@]}" -C "$A_W" push -q origin main v1.0.0 2>/dev/null
A="$("${G[@]}" -C "$A_W" rev-parse HEAD)"

# Der Checkout des Produkts — auf A, bevor es mehr gibt.
CO="$T/co"
"${G[@]}" clone -q "$T/origin.git" "$CO" 2>/dev/null
printf 'POSTGRES_USER=magister\nPOSTGRES_DB=magister\n' >"$CO/deploy/compose/.env"
mkdir -p "$CO/plattform/certs"
age-keygen -o "$CO/plattform/certs/backup-age.key" 2>/dev/null
grep -o 'age1[0-9a-z]*' "$CO/plattform/certs/backup-age.key" | head -1 >"$DZ/pub"
printf 'public=0001' >"$DZ/db"

echo b >"$A_W/VERSION"; commit "B"
B="$("${G[@]}" -C "$A_W" rev-parse HEAD)"
"${G[@]}" -C "$A_W" checkout -q -b kaputt-migration
printf 'public=0002' >"$A_W/deploy/compose/schema"; touch "$A_W/deploy/compose/kaputt"; commit "C"
C="$("${G[@]}" -C "$A_W" rev-parse HEAD)"
"${G[@]}" -C "$A_W" checkout -q -b kaputt-gleich main
touch "$A_W/deploy/compose/kaputt"; commit "D"
"${G[@]}" -C "$A_W" checkout -q -b aufbau-kaputt main
touch "$A_W/deploy/compose/aufbau-kaputt"; commit "E"
"${G[@]}" -C "$A_W" push -q origin main kaputt-migration kaputt-gleich aufbau-kaputt 2>/dev/null

# --- Attrappen -------------------------------------------------------------------
cat >"$T/bin/docker" <<'X'
#!/usr/bin/env bash
echo "docker $*" >>"$DZ/docker"
if [ "${1:-}" = info ]; then [ ! -f "$DZ/docker-aus" ]; exit $?; fi
[ "${1:-}" = compose ] || exit 0
shift
dir=""
while [ $# -gt 0 ]; do
  case "$1" in
    --project-directory) dir="$2"; shift 2 ;;
    -f) shift 2 ;;
    *) break ;;
  esac
done
kaputt=0; [ -f "$dir/kaputt" ] && kaputt=1
befehl="$1"; shift
case "$befehl" in
  config) printf '%s\n' postgres magister-api magister-web caddy pg-backup ;;
  ps)
    api=healthy; [ "$kaputt" = 1 ] && api=unhealthy
    printf '%s\n' "postgres running healthy" "magister-api running $api" \
      "magister-web running " "caddy running " "pg-backup running " ;;
  restart|stop) echo "$befehl $*" >>"$DZ/compose" ;;
  exec)
    art=""
    while [ $# -gt 0 ]; do
      case "$1" in
        -T) shift ;;
        -e) case "$2" in BACKUP_ART=*) art="${2#BACKUP_ART=}" ;; esac; shift 2 ;;
        *) break ;;
      esac
    done
    dienst="$1"; shift
    case "$dienst:$1" in
      magister-api:python) [ "$kaputt" = 1 ] && exit 1; echo ok ;;
      pg-backup:/usr/local/bin/backup.sh)
        [ -f "$DZ/sicherung-kaputt" ] && { echo "[pg-backup] FEHLER" >&2; exit 1; }
        n=$(( $(cat "$DZ/zaehler" 2>/dev/null || echo 0) + 1 )); echo "$n" >"$DZ/zaehler"
        name="magister-$(printf '20261116T1200%02dZ' "$n")"
        if [ "$art" = rueckfall ] && [ ! -f "$DZ/pg-backup-alt" ]; then name="$name-rueckfall"; fi
        name="$name.dump.age"
        echo "[pg-backup] Sicherung startet: /var/backups/magister/$name"
        age -r "$(cat "$DZ/pub")" -o "$DZ/sicherungen/$name" <"$DZ/db" || exit 1
        (cd "$DZ/sicherungen" && sha256sum "$name" >>PRUEFSUMMEN.sha256)
        echo "[pg-backup] fertig" ;;
      pg-backup:cat) cat "$DZ/sicherungen/${2##*/}" ;;
      pg-backup:ls) ls -1 "$DZ/sicherungen" ;;
      pg-backup:sh) sh -c "$3" _ "$DZ/sicherungen" "$6" ;;
      postgres:psql)
        sql=""; db=""
        while [ $# -gt 0 ]; do
          case "$1" in -c) sql="$2"; shift 2 ;; -d) db="$2"; shift 2 ;; *) shift ;; esac
        done
        printf '%s | %s\n' "$db" "$sql" >>"$DZ/sql"
        case "$sql" in
          *alembic_version*) [ -f "$DZ/db" ] || exit 1; cat "$DZ/db"; echo ;;
          *'"magister" RENAME TO'*) mv "$DZ/db" "$DZ/beiseite" ;;
          *'RENAME TO "magister"'*) mv "$DZ/beiseite" "$DZ/db" ;;
          *'DROP DATABASE'*) rm -f "$DZ/db" ;;
        esac ;;
      postgres:pg_restore)
        if [[ " $* " == *" -f /dev/null "* ]]; then cat >/dev/null; else cat >"$DZ/db"; fi ;;
      *) echo "Attrappe kennt nicht: $dienst $*" >&2; exit 1 ;;
    esac ;;
esac
exit 0
X
printf '#!/usr/bin/env bash\nexit 0\n' >"$T/bin/sleep"
chmod +x "$T/bin/"*

# --- Aufruf ------------------------------------------------------------------------
# So wie der Agent: im Checkout, ohne Terminal, nur PATH/LANG/BETRIEB_AUFTRAG
# (dazu DZ für die Attrappen und kurze Wartezeiten).
ZUSATZ_ENV=()  # weitere Umgebung für einen Lauf (z. B. DOCKER_CONFIG vom Agenten)
lauf() {  # Argumente für betrieb.sh -> RC; stdout in $T/out, stderr in $T/err
  (cd "$CO" && env -i PATH="$T/bin:$PATH" LANG=C.UTF-8 BETRIEB_AUFTRAG="auftrag-$RANDOM" \
     DZ="$DZ" BETRIEB_HEALTH_SEK=10 BETRIEB_RUECKFALL_HEALTH_SEK=10 \
     ${ZUSATZ_ENV[@]+"${ZUSATZ_ENV[@]}"} \
     ./scripts/betrieb.sh "$@" </dev/null >"$T/out" 2>"$T/err")
  RC=$?
  AKTION_ERWARTET="${1:-}"
  json_pruefen
}

#: stdout ist genau eine Zeile, gültiges JSON nach betrieb/v1.
json_pruefen() {
  local fehler
  fehler="$(python3 - "$T/out" "$AKTION_ERWARTET" <<'PY'
import json, re, sys
text = open(sys.argv[1], encoding="utf-8").read()
zeilen = text.splitlines()
try:
    assert len(zeilen) == 1 and text.endswith("\n"), f"nicht genau eine Zeile: {text!r}"
    d = json.loads(zeilen[0])
    assert d["format"] == "betrieb/v1" and d["produkt"] == "magister", d
    assert d["aktion"] == sys.argv[2], d["aktion"]
    assert isinstance(d["ok"], bool), "ok"
    assert isinstance(d["meldung"], str) and 0 < len(d["meldung"]) <= 300, "meldung"
    s = d["stand"]
    assert set(s) == {"version", "commit", "quelle", "kanal", "gesund",
                      "zurueck_moeglich", "vorher", "letzte_sicherung"}, sorted(s)
    assert s["quelle"] == "git" and s["kanal"] is None, "quelle/kanal"
    assert s["commit"] is None or re.fullmatch(r"[0-9a-f]{40}", s["commit"]), "commit"
    assert s["vorher"] is None or set(s["vorher"]) == {"version", "commit", "zeit"}, "vorher"
    for k in ("gesund", "zurueck_moeglich"):
        assert s[k] is None or isinstance(s[k], bool), k
except Exception as exc:  # noqa: BLE001
    print(exc)
PY
)"
  pruefe "  … stdout: eine Zeile betrieb/v1" "" "$fehler"
}

#: Ein Feld der Antwort: wert stand vorher commit
wert() {
  python3 - "$T/out" "$@" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
for k in sys.argv[2:]:
    d = d.get(k) if isinstance(d, dict) else None
print("null" if d is None else (str(d).lower() if isinstance(d, bool) else d))
PY
}

head_co() { git -C "$CO" rev-parse HEAD; }
branch_co() { git -C "$CO" symbolic-ref -q --short HEAD || echo losgelöst; }
zeilen() { if [ -f "$1" ]; then wc -l <"$1" | tr -d ' '; else echo 0; fi; }
sicherungen() { find "$DZ/sicherungen" -name '*.dump.age' | wc -l | tr -d ' '; }
db() { cat "$DZ/db" 2>/dev/null || echo fehlt; }

#: Nichts geändert: HEAD, Aufbau, Sicherungen wie vorher.
nichts_geaendert() {  # $1 = Beschreibung
  pruefe "$1: HEAD unverändert" "$VOR_HEAD" "$(head_co)"
  pruefe "$1: kein plattform-aufbau.sh" "$VOR_AUFBAU" "$(zeilen "$DZ/aufbau")"
  pruefe "$1: keine Sicherung" "$VOR_SICHERUNGEN" "$(sicherungen)"
}
merken() { VOR_HEAD="$(head_co)"; VOR_AUFBAU="$(zeilen "$DZ/aufbau")"; VOR_SICHERUNGEN="$(sicherungen)"; }

# =================================================================================
printf '\n\033[1m1 · stand\033[0m\n'
lauf stand
pruefe "Exit 0" 0 "$RC"
pruefe "Version aus git (Tag)" v1.0.0 "$(wert stand version)"
pruefe "Commit" "$A" "$(wert stand commit)"
pruefe "gesund" true "$(wert stand gesund)"
pruefe "zurück nicht möglich (kein Update)" false "$(wert stand zurueck_moeglich)"
pruefe "vorher leer" null "$(wert stand vorher)"
pruefe "noch keine Sicherung" null "$(wert stand letzte_sicherung)"

printf '\n\033[1m2 · abgelehnt, nichts geändert\033[0m\n'
merken
for falsch in "-x" "a..b" "HEAD" "a b" "x@{1}" "\$(touch $T/gehackt)"; do
  lauf aktualisieren --ref "$falsch"
  pruefe "ungültige Ref '$falsch' → Exit 3" 3 "$RC"
done
lauf aktualisieren --version 1.2.0 --manifest m.json --signatur m.sig
pruefe "Manifest-Form → Exit 3 (Magister aus git)" 3 "$RC"
lauf aktualisieren
pruefe "ohne --ref → Exit 3" 3 "$RC"
lauf stand extra
pruefe "stand mit Argument → Exit 3" 3 "$RC"
lauf loeschen
pruefe "unbekannte Aktion → Exit 3" 3 "$RC"
pruefe "unbekannte Aktion: aktion im JSON" loeschen "$(wert aktion)"
lauf aktualisieren --ref gibt-es-nicht
pruefe "unbekannte Ref → Exit 3" 3 "$RC"
pruefe "unbekannte Ref: ok false" false "$(wert ok)"
echo lokal >>"$CO/VERSION"
lauf aktualisieren --ref main
pruefe "lokale Änderung → Exit 3" 3 "$RC"
pruefe "lokale Änderung: in der Meldung" ja "$(enthaelt "lokale Änderung" "$(wert meldung)")"
git -C "$CO" checkout -q -- VERSION
nichts_geaendert "abgelehnt"
pruefe "keine Ausführung aus der Ref" nein "$(if [ -e "$T/gehackt" ]; then echo ja; else echo nein; fi)"

printf '\n\033[1m3 · gleiche Version\033[0m\n'
merken
lauf aktualisieren --ref v1.0.0
pruefe "gleiche Version → Exit 0" 0 "$RC"
pruefe "Meldung: schon auf" "schon auf v1.0.0" "$(wert meldung)"
nichts_geaendert "schon auf"

printf '\n\033[1m4 · Update auf main\033[0m\n'
lauf aktualisieren --ref main
pruefe "Exit 0" 0 "$RC"
pruefe "ok" true "$(wert ok)"
pruefe "HEAD auf B" "$B" "$(head_co)"
pruefe "Branch main angehängt" main "$(branch_co)"
pruefe "plattform-aufbau.sh update auf B, ohne Fragen" "update $B fragen=1" "$(tail -n 1 "$DZ/aufbau")"
pruefe "seine Ausgabe auf stderr, nicht stdout" ja "$(enthaelt "aufbau-ausgabe auf stdout" "$(cat "$T/err")")"
pruefe "eine Rückfall-Sicherung" 1 "$(find "$DZ/sicherungen" -name '*-rueckfall.dump.age' | wc -l | tr -d ' ')"
pruefe "Sicherung verschlüsselt (kein Klartext)" nein "$(enthaelt public= "$(cat "$DZ"/sicherungen/*.dump.age)")"
pruefe "vorher = A" "$A" "$(wert stand vorher commit)"
pruefe "vorher Version" v1.0.0 "$(wert stand vorher version)"
pruefe "zurück möglich" true "$(wert stand zurueck_moeglich)"
pruefe "letzte Sicherung" 2026-11-16T12:00:01Z "$(wert stand letzte_sicherung)"
pruefe "Meldung" "v1.0.0 → $(git -C "$CO" describe --tags "$B"), Health ok" "$(wert meldung)"
pruefe "Zustand nur für root lesbar" 600 "$(stat -c %a "$CO/plattform/betrieb/zustand")"
pruefe "Checkout sauber (Sperre ignoriert)" "" "$(git -C "$CO" status --porcelain)"

printf '\n\033[1m5 · älter → abgelehnt\033[0m\n'
merken
lauf aktualisieren --ref v1.0.0
pruefe "ältere Version → Exit 3" 3 "$RC"
pruefe "Meldung nennt zurueck" ja "$(enthaelt "zurück nur über zurueck" "$(wert meldung)")"
nichts_geaendert "älter"

printf '\n\033[1m6 · zurueck, genau einmal\033[0m\n'
: >"$DZ/sql"
lauf zurueck
pruefe "Exit 0" 0 "$RC"
pruefe "HEAD auf A" "$A" "$(head_co)"
pruefe "Branch main wieder angehängt" main "$(branch_co)"
pruefe "Datenbank aus der Sicherung (bisherige umbenannt)" ja \
  "$(enthaelt '"magister" RENAME TO "magister_vor_rueckfall_' "$(cat "$DZ/sql")")"
pruefe "Datenbank nicht gelöscht" nein "$(enthaelt 'DROP DATABASE' "$(cat "$DZ/sql")")"
pruefe "zurück nicht mehr möglich" false "$(wert stand zurueck_moeglich)"
merken
lauf zurueck
pruefe "zweites zurueck → Exit 3" 3 "$RC"
nichts_geaendert "zweites zurueck"
rm -f "$DZ/beiseite"

lauf aktualisieren --ref main
pruefe "wieder auf main → Exit 0" 0 "$RC"

printf '\n\033[1m7 · sichern, neustart, Sperre\033[0m\n'
lauf sichern
pruefe "sichern → Exit 0" 0 "$RC"
pruefe "letzte Sicherung ist die neue" 2026-11-16T12:00:03Z "$(wert stand letzte_sicherung)"
pruefe "Meldung nennt die Datei" ja "$(enthaelt "magister-20261116T120003Z-rueckfall.dump.age" "$(wert meldung)")"
touch "$DZ/sicherung-kaputt"
lauf sichern
pruefe "sichern scheitert → Exit 2" 2 "$RC"
rm -f "$DZ/sicherung-kaputt"

AUFBAU_VOR="$(zeilen "$DZ/aufbau")"
lauf neustart
pruefe "neustart → Exit 0" 0 "$RC"
pruefe "docker compose restart der Datenebene" "restart " "$(tail -n 1 "$DZ/compose")"
pruefe "kein plattform-aufbau.sh (kein Neubau)" "$AUFBAU_VOR" "$(zeilen "$DZ/aufbau")"

( flock 9; : >"$T/gesperrt"; exec /bin/sleep 60 ) 9>>"$CO/.betrieb.lock" &
HALTER=$!
for _ in $(seq 50); do [ -f "$T/gesperrt" ] && break; /bin/sleep 0.1; done
merken
lauf aktualisieren --ref kaputt-gleich
pruefe "Sperre belegt → Exit 4" 4 "$RC"
pruefe "belegt: gesund nicht geprüft" null "$(wert stand gesund)"
nichts_geaendert "belegt"
kill "$HALTER" 2>/dev/null; wait "$HALTER" 2>/dev/null; HALTER=""

touch "$DZ/docker-aus"
lauf stand
pruefe "Docker antwortet nicht: stand Exit 0" 0 "$RC"
pruefe "Docker antwortet nicht: gesund false" false "$(wert stand gesund)"
rm -f "$DZ/docker-aus"

printf '\n\033[1m8 · Health scheitert → selbst zurück (Code und Datenbank)\033[0m\n'
: >"$DZ/sql"
lauf aktualisieren --ref kaputt-migration
pruefe "Exit 1" 1 "$RC"
pruefe "ok false" false "$(wert ok)"
pruefe "HEAD wieder B" "$B" "$(head_co)"
pruefe "Branch main wieder angehängt" main "$(branch_co)"
pruefe "Datenbank wieder auf dem alten Schemastand" public=0001 "$(db)"
pruefe "bisherige Datenbank umbenannt, nicht gelöscht" ja "$(enthaelt 'RENAME TO "magister_vor_rueckfall_' "$(cat "$DZ/sql")")"
pruefe "Aufbau: neu, dann alt" "update $C fragen=1|update $B fragen=1" "$(tail -n 2 "$DZ/aufbau" | paste -sd'|' -)"
pruefe "vorher bleibt das letzte erfolgreiche Update (A)" "$A" "$(wert stand vorher commit)"
pruefe "Meldung: zurück" ja "$(enthaelt "zurück auf" "$(wert meldung)")"
pruefe "gesund" true "$(wert stand gesund)"
rm -f "$DZ/beiseite"

merken
touch "$DZ/sicherung-kaputt"
lauf aktualisieren --ref kaputt-gleich
pruefe "Sicherung scheitert → Exit 3" 3 "$RC"
nichts_geaendert "Sicherung gescheitert"
rm -f "$DZ/sicherung-kaputt"

lauf aktualisieren --ref aufbau-kaputt
pruefe "plattform-aufbau.sh scheitert → Exit 1" 1 "$RC"
pruefe "HEAD wieder B" "$B" "$(head_co)"
rm -f "$DZ/beiseite"

printf '\n\033[1m9 · ohne privaten Schlüssel\033[0m\n'
mv "$CO/plattform/certs/backup-age.key" "$T/schluessel"
: >"$DZ/sql"
lauf aktualisieren --ref kaputt-gleich
pruefe "Schemastand gleich → nur Code zurück, Exit 1" 1 "$RC"
pruefe "HEAD wieder B" "$B" "$(head_co)"
pruefe "Datenbank nicht angefasst" nein "$(enthaelt RENAME "$(cat "$DZ/sql")")"
pruefe "Meldung: Datenbank unverändert" ja "$(enthaelt "Datenbank unverändert" "$(wert meldung)")"

lauf aktualisieren --ref kaputt-migration
pruefe "Schemastand geändert → Exit 2" 2 "$RC"
pruefe "bleibt auf dem neuen Stand (nichts halb zurück)" "$C" "$(head_co)"
pruefe "Meldung nennt den Schlüssel und zurueck" ja \
  "$(enthaelt "plattform/certs/backup-age.key legen, dann zurueck" "$(wert meldung)")"
pruefe "zurück jetzt nicht möglich" false "$(wert stand zurueck_moeglich)"
merken
lauf zurueck
pruefe "zurueck ohne Schlüssel → Exit 3" 3 "$RC"
nichts_geaendert "zurueck ohne Schlüssel"

mv "$T/schluessel" "$CO/plattform/certs/backup-age.key"
lauf stand
pruefe "mit Schlüssel: zurück möglich" true "$(wert stand zurueck_moeglich)"
lauf zurueck
pruefe "zurueck → Exit 0" 0 "$RC"
pruefe "HEAD wieder B" "$B" "$(head_co)"
pruefe "Branch main" main "$(branch_co)"
pruefe "Datenbank wieder public=0001" public=0001 "$(db)"
rm -f "$DZ/beiseite"
lauf zurueck
pruefe "zweites zurueck → Exit 3" 3 "$RC"

printf '\n\033[1m10 · alter pg-backup (ohne Eigentümer und Rechte)\033[0m\n'
touch "$DZ/pg-backup-alt"
lauf sichern
pruefe "sichern → Exit 0" 0 "$RC"
pruefe "Meldung: pg-backup neu bauen" ja "$(enthaelt "pg-backup ist alt" "$(wert meldung)")"
rm -f "$DZ/pg-backup-alt"

printf '\n\033[1m11 · Repo privat: Stand aus dem Bundle des Cockpits, origin nie kontaktiert\033[0m\n'
# Neue Stände nur im Arbeits-Klon (nie nach origin): F auf main (Tag v1.1.0),
# G auf „weiter" (Tag v1.2.0), X auf „fremd" (nie in einem Bundle).
"${G[@]}" -C "$A_W" checkout -q main
echo f >"$A_W/VERSION"; commit "F"; "${G[@]}" -C "$A_W" tag v1.1.0
F="$("${G[@]}" -C "$A_W" rev-parse HEAD)"
"${G[@]}" -C "$A_W" checkout -q -b weiter
echo g >"$A_W/VERSION"; commit "G"; "${G[@]}" -C "$A_W" tag v1.2.0
G_C="$("${G[@]}" -C "$A_W" rev-parse HEAD)"
"${G[@]}" -C "$A_W" checkout -q -b fremd main
echo x >"$A_W/VERSION"; commit "X"
X="$("${G[@]}" -C "$A_W" rev-parse HEAD)"
mkdir -m 700 "$T/agent"
"${G[@]}" -C "$A_W" bundle create -q "$T/agent/main.bundle" main v1.1.0 2>/dev/null
"${G[@]}" -C "$A_W" bundle create -q "$T/agent/tag.bundle" "$F..v1.2.0" 2>/dev/null
"${G[@]}" -C "$A_W" bundle create -q "$T/agent/alt.bundle" v1.0.0 2>/dev/null
echo "kein Bundle" >"$T/agent/kaputt.bundle"

# origin: ungültige Adresse, jede Verbindung hinterlässt eine Marke
cat >"$T/bin/falle-upload-pack" <<X
#!/bin/sh
echo kontakt >>"$T/origin-kontaktiert"
echo "ERROR: Repository not found." >&2
exit 128
X
chmod +x "$T/bin/falle-upload-pack"
git -C "$CO" remote set-url origin /nicht/vorhanden/magister.git
git -C "$CO" config remote.origin.uploadpack "$T/bin/falle-upload-pack"
kontakt() { if [ -e "$T/origin-kontaktiert" ]; then echo ja; else echo nein; fi; }
upstream() { git -C "$CO" config --get "branch.$1.remote" || echo ohne; }

# docker erbt den Pull-Zugang des Agenten
mv "$T/bin/docker" "$T/bin/docker-attrappe"
cat >"$T/bin/docker" <<X
#!/usr/bin/env bash
echo "\${DOCKER_CONFIG-ohne}" >>"$DZ/docker-config"
exec "$T/bin/docker-attrappe" "\$@"
X
chmod +x "$T/bin/docker"
mkdir -m 700 "$T/docker-zugang-nur-fuer-diesen-auftrag"

merken
for fall in "alt.bundle|$F|fehlt im Bundle" "kaputt.bundle|$F|Bundle ungültig" \
            "gibt-es-nicht.bundle|$F|Bundle fehlt" "main.bundle|${F:0:39}|kein Commit" \
            "main.bundle|$X|fehlt im Bundle"; do
  IFS='|' read -r datei c text <<<"$fall"
  lauf aktualisieren --ref main --bundle "$T/agent/$datei" --commit "$c"
  pruefe "$datei, ${c:0:8}… → Exit 3" 3 "$RC"
  pruefe "$datei: Meldung „$text\"" ja "$(enthaelt "$text" "$(wert meldung)")"
done
lauf aktualisieren --ref main --bundle "$T/agent/main.bundle"
pruefe "--bundle ohne --commit → Exit 3" 3 "$RC"
lauf aktualisieren --ref main --commit "$F"
pruefe "--commit ohne --bundle → Exit 3" 3 "$RC"
lauf aktualisieren --ref main --bundle "$T/agent/main.bundle" --bundle "$T/agent/main.bundle" --commit "$F"
pruefe "--bundle zweimal → Exit 3" 3 "$RC"
nichts_geaendert "Bundle abgelehnt"
pruefe "abgelehnt: origin nie kontaktiert" nein "$(kontakt)"

ZUSATZ_ENV=(DOCKER_CONFIG="$T/docker-zugang-nur-fuer-diesen-auftrag")
lauf aktualisieren --ref main --bundle "$T/agent/main.bundle" --commit "$F"
ZUSATZ_ENV=()
pruefe "main aus dem Bundle → Exit 0" 0 "$RC"
pruefe "HEAD auf F" "$F" "$(head_co)"
pruefe "Branch main angehängt" main "$(branch_co)"
pruefe "Branch ohne Upstream" ohne "$(upstream main)"
pruefe "Version aus dem Tag des Bundles" v1.1.0 "$(wert stand version)"
pruefe "plattform-aufbau.sh update auf F" "update $F fragen=1" "$(tail -n 1 "$DZ/aufbau")"
pruefe "origin nie kontaktiert" nein "$(kontakt)"
pruefe "docker erbt DOCKER_CONFIG" "$T/docker-zugang-nur-fuer-diesen-auftrag" \
  "$(sort -u "$DZ/docker-config" | grep -v '^ohne$')"
pruefe "DOCKER_CONFIG nie in Antwort oder Journal" nein \
  "$(enthaelt docker-zugang-nur "$(cat "$T/out" "$T/err")")"

lauf aktualisieren --ref v1.2.0 --bundle "$T/agent/tag.bundle" --commit "$G_C"
pruefe "Tag aus einem dünnen Bundle → Exit 0" 0 "$RC"
pruefe "HEAD auf G" "$G_C" "$(head_co)"
pruefe "Tag: losgelöst" losgelöst "$(branch_co)"
pruefe "Version v1.2.0" v1.2.0 "$(wert stand version)"
pruefe "vorher = F" "$F" "$(wert stand vorher commit)"

lauf zurueck
pruefe "zurueck ohne origin → Exit 0" 0 "$RC"
pruefe "HEAD wieder F" "$F" "$(head_co)"
pruefe "Branch main" main "$(branch_co)"
rm -f "$DZ/beiseite"
pruefe "origin nie kontaktiert (zurueck)" nein "$(kontakt)"

lauf aktualisieren --ref main
pruefe "ohne Bundle, origin privat → Exit 3" 3 "$RC"
pruefe "Meldung verweist auf das Bundle aus dem Cockpit" ja \
  "$(enthaelt "Code als Bundle aus dem Cockpit" "$(wert meldung)")"
pruefe "ohne Bundle fragt es origin" ja "$(kontakt)"

git -C "$CO" remote remove origin
lauf stand
pruefe "stand ganz ohne Remote → Exit 0" 0 "$RC"
pruefe "stand ohne Remote: Commit" "$F" "$(wert stand commit)"

printf '\n%s ok, %s fehlgeschlagen\n' "$GRUEN" "$ROT"
[ "$ROT" -eq 0 ] || { echo "--- stderr des letzten Laufs ---"; cat "$T/err"; exit 1; }
echo "betrieb: bestanden"
