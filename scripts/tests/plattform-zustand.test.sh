#!/usr/bin/env bash
# Der Zustandsbericht für die Überwachung (scripts/plattform_zustand.py).
#
# Ohne Docker und ohne Netz: docker, ss und curl sind Attrappen, die genau die
# Lage vom Dev-Host nachstellen — der Caddy aus dem Debian-Paket auf :80, ein
# Container, der nicht läuft, ein Kunde in Wartung. Geprüft wird, dass der
# Bericht jedes davon als Störung meldet, mit Grund, und eine untergeschobene
# Zielliste nicht ausführt.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/plattform/ops" "$T/plattform/certs"
printf 'PLATTFORM_DOMAIN=beispiel.ch\nPLATTFORM_BIND=10.0.0.5\n' > "$T/plattform/plattform.conf"

cat > "$T/bin/docker" <<'X'
#!/usr/bin/env bash
case "$*" in
  *project=deploy*) printf 'api\trunning\tUp 3 hours (healthy)\tdeploy-api-1\ncaddy\trunning\tUp 3 hours\tdeploy-caddy-1\n' ;;
  *project=magister*) printf 'magister-api\trunning\tUp 1 hour (healthy)\tmagister-magister-api-1\ncaddy\tcreated\tCreated\tmagister-caddy-1\n' ;;
esac
X
cat > "$T/bin/ss" <<'X'
#!/usr/bin/env bash
case "$*" in
  *":80"*) echo 'LISTEN 0 4096 *:80 *:* users:(("caddy",pid=1272,fd=7))' ;;
  *":4444"*) echo 'LISTEN 0 4096 10.0.0.5:4444 0.0.0.0:* users:(("docker-proxy",pid=99,fd=4))' ;;
  *) : ;;
esac
X
cat > "$T/bin/curl" <<'X'
#!/usr/bin/env bash
# Letztes Argument ist die URL.
for url; do :; done
case "$url" in
  http://*) printf '200' ;;                       # fremder Caddy: Begrüssungsseite statt Umleitung
  *:4444/api/health) printf '200' ;;
  *:46200/*) printf '401' ;;
  https://hwb.beispiel.ch/*) printf '503' ;;
  https://gmp.beispiel.ch/*) printf '401' ;;
  *) printf '000'; exit 7 ;;
esac
X
cat > "$T/bin/openssl" <<'X'
#!/usr/bin/env bash
echo "notAfter=Jan  1 00:00:00 2099 GMT"
X
chmod +x "$T/bin/"*
touch "$T/plattform/certs/tenants.pem"
cat > "$T/plattform/ops/probe-targets.json" <<'X'
[{"slug": "gmp", "hostname": "gmp.beispiel.ch"},
 {"slug": "hwb", "hostname": "hwb.beispiel.ch"},
 {"slug": "boese", "hostname": "x;touch /tmp/gehackt"}]
X

PATH="$T/bin:$PATH" python3 "$REPO/scripts/plattform_zustand.py" --ops "$T/plattform/ops"

python3 - "$T/plattform/ops/health.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
fehler = []
def soll(bedingung, text):
    print(("  ok  " if bedingung else "  !!  ") + text)
    if not bedingung:
        fehler.append(text)

dienste = {(s["stack"], s["service"]): s for s in r["services"]}
soll(dienste[("konsole", "api")]["ok"], "laufender, gesunder Dienst ist in Ordnung")
soll(not dienste[("daten", "caddy")]["ok"], "nur angelegter Caddy der Datenebene ist eine Störung")

ports = {p["port"]: p for p in r["ports"]}
soll(not ports[80]["ok"] and "caddy" in ports[80]["detail"], "fremder Caddy auf :80 wird mit Namen gemeldet")
soll(ports[4444]["ok"], "docker-proxy auf :4444 ist dieser Stack")
soll(not ports[443]["ok"] and ports[443]["detail"] == "niemand lauscht", "leerer Port 443 wird gemeldet")

proben = {p["name"]: p for p in r["probes"]}
soll(not proben["Port 80 leitet auf HTTPS um"]["ok"], "200 statt Umleitung auf :80 ist eine Störung")
soll(proben["Connector-Kanal antwortet (46200)"]["ok"], "401 auf dem Connector-Kanal ist in Ordnung")
gmp = [p for n, p in proben.items() if n.startswith("Kunde gmp")][0]
hwb = [p for n, p in proben.items() if n.startswith("Kunde hwb")][0]
soll(gmp["ok"] and gmp["detail"] == "bedient", "Kunde mit 401 gilt als bedient")
soll(not hwb["ok"] and "Wartung" in hwb["detail"], "Kunde mit 503 gilt als Wartung")
soll(not any("boese" in n for n in proben), "untergeschobener Hostname wird nicht geprobt")

soll(r["certificates"][0]["ok"], "Zertifikat mit langer Laufzeit ist in Ordnung")
soll(r["ok"] is False, "Gesamtzustand ist Störung")
sys.exit(1 if fehler else 0)
PY
test ! -e /tmp/gehackt
echo "plattform-zustand: bestanden"
