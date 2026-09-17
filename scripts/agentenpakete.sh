#!/usr/bin/env bash
# Die Pakete des Connector-Agenten dorthin bringen, wo die Konsole sie
# ausliefert (ADR-0014).
#
#   ./scripts/agentenpakete.sh holen          # aus der CI holen (MSI + .deb)
#   ./scripts/agentenpakete.sh bauen          # was hier baubar ist (.deb)
#   ./scripts/agentenpakete.sh msi <payload>  # MSI aus einem Windows-Payload
#   ./scripts/agentenpakete.sh zeigen         # was im Verzeichnis liegt
#
# **Warum es dieses Skript gibt.** Die CI baut MSI und .deb bei jedem Push
# (agent-ci.yml) — aber sie legt sie als Workflow-Artefakte ab, und die liegen
# in GitHub, nicht auf dem Plattform-Server. Zwischen „gebaut" und
# „herunterladbar" fehlte der Weg; im Runbook stand ein `cp` mit einem
# Dateinamen, den es auf keiner Maschine gab.
#
# **Warum das MSI zweigeteilt ist.** PyInstaller friert die Laufzeit ein, auf
# der es selbst läuft — der eingefrorene Agent (das „Payload") entsteht nur
# unter Windows. Das MSI drumherum baut Linux mit `wixl`
# (agent/packaging/windows/README.md). Zwei Wege zum fertigen MSI:
#
#   `holen` — aus der CI. Der normale Weg, sobald agent-ci.yml auf `main`
#             liegt und gelaufen ist.
#   `msi`   — aus einem Payload, das jemand auf einer Windows-Maschine mit
#             `agent/packaging/windows/build-payload.ps1` gebaut hat. Der Weg,
#             wenn die CI noch keines hat.
#
# `bauen` macht nur das .deb. Es legt bewusst KEINEN Platzhalter aus
# `build-msi.sh --stub` ab: der ist installierbar und ohne Inhalt, und
# niemand soll ihn im Paketverzeichnis für ein Paket halten.
#
# Zugang für `holen`: ein Token mit `actions:read` auf dem Repository, in
# GITHUB_TOKEN oder in ~/.magister/github-token (0600). Es wird nie
# ausgegeben und steht in keiner Prozessliste — curl liest es aus einer
# Datei.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW="agent-ci.yml"
ZWEIG="${AGENT_CI_ZWEIG:-main}"
# Die Artefaktnamen, die agent-ci.yml hochlädt.
ARTEFAKTE=("magister-connector-msi" "magister-connector-deb")

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m !  %s\033[0m\n' "$*"; }
die()  { printf '\033[31m !! %s\033[0m\n' "$*" >&2; exit 1; }

# --- Wohin ------------------------------------------------------------------
# Derselbe Pfad, den die Konsole liest. Er steht in ihrer Umgebung; ihn hier
# noch einmal zu erraten wäre die zweite Quelle für dieselbe Wahrheit.
ziel_verzeichnis() {
  local aus_env=""
  if [ -f "$REPO/cockpit/deploy/.env" ]; then
    aus_env="$(grep -oP '(?<=^COCKPIT_AGENT_PACKAGE_DIR=).*' "$REPO/cockpit/deploy/.env" || true)"
  fi
  local pfad="${AGENT_PAKETE_ZIEL:-$aus_env}"
  [ -n "$pfad" ] || die "Kein Paketverzeichnis: COCKPIT_AGENT_PACKAGE_DIR fehlt in cockpit/deploy/.env (erst 'plattform-aufbau.sh up')."
  mkdir -p "$pfad"
  printf '%s' "$pfad"
}

# --- Zugang -----------------------------------------------------------------
token_datei() {
  # Eine DATEI und keine Variable auf der Kommandozeile: curl liest sie mit
  # `--config`, damit das Geheimnis weder in der Prozessliste noch in der
  # Shell-History steht.
  local ablage="$HOME/.magister/github-token"
  local wert="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
  if [ -z "$wert" ] && [ -f "$ablage" ]; then
    wert="$(tr -d '\n' < "$ablage")"
  fi
  [ -n "$wert" ] || die "Kein Token. GITHUB_TOKEN setzen oder $ablage anlegen (Recht: actions:read)."
  local konf
  konf="$(mktemp)"
  chmod 600 "$konf"
  printf 'header = "Authorization: Bearer %s"\n' "$wert" > "$konf"
  printf 'header = "Accept: application/vnd.github+json"\n' >> "$konf"
  printf '%s' "$konf"
}

eigentuemer_repo() {
  local url
  url="$(git -C "$REPO" remote get-url origin 2>/dev/null || true)"
  [ -n "$url" ] || die "Kein origin-Remote — Repository nicht bestimmbar."
  printf '%s' "$url" | sed -E 's#^git@github\.com:#https://github.com/#; s#\.git$##' \
    | sed -E 's#^https://[^/]+/##'
}

# --- Holen ------------------------------------------------------------------
cmd_holen() {
  command -v curl >/dev/null || die "curl fehlt."
  command -v unzip >/dev/null || die "unzip fehlt (apt-get install unzip)."
  command -v python3 >/dev/null || die "python3 fehlt."

  local ziel slug konf
  ziel="$(ziel_verzeichnis)"
  slug="$(eigentuemer_repo)"
  konf="$(token_datei)"
  # shellcheck disable=SC2064  # $konf soll JETZT eingesetzt werden.
  trap "rm -f '$konf'" EXIT

  say "Letzten erfolgreichen Lauf von $WORKFLOW auf '$ZWEIG' suchen ($slug)"
  local lauf
  lauf="$(curl -sS --config "$konf" \
    "https://api.github.com/repos/$slug/actions/workflows/$WORKFLOW/runs?branch=$ZWEIG&status=success&per_page=1" \
    | python3 -c '
import json, sys
daten = json.load(sys.stdin)
laeufe = daten.get("workflow_runs") or []
if not laeufe:
    sys.exit(0)
lauf = laeufe[0]
# Kein f-string mit Anführungszeichen darin: vor Python 3.12 ein Syntaxfehler,
# und dieses Skript läuft auch auf älteren Servern.
print("%s\t%s\t%s" % (lauf["id"], lauf["head_sha"][:8], lauf["created_at"]))
')"
  if [ -z "$lauf" ]; then
    die "Kein erfolgreicher Lauf auf '$ZWEIG'. Anderer Zweig: AGENT_CI_ZWEIG=<zweig> $0 holen"
  fi
  local lauf_id sha wann
  lauf_id="$(printf '%s' "$lauf" | cut -f1)"
  sha="$(printf '%s' "$lauf" | cut -f2)"
  wann="$(printf '%s' "$lauf" | cut -f3)"
  say "Lauf $lauf_id (Stand $sha, $wann)"

  local liste
  liste="$(curl -sS --config "$konf" \
    "https://api.github.com/repos/$slug/actions/runs/$lauf_id/artifacts?per_page=100")"

  local geholt=0
  for name in "${ARTEFAKTE[@]}"; do
    local id
    id="$(printf '%s' "$liste" | python3 -c '
import json, sys
name = sys.argv[1]
for a in json.load(sys.stdin).get("artifacts", []):
    if a["name"] == name:
        print(a["id"] if not a["expired"] else "abgelaufen")
        break
' "$name")"
    if [ -z "$id" ]; then
      warn "$name: in diesem Lauf nicht vorhanden."
      continue
    fi
    if [ "$id" = "abgelaufen" ]; then
      warn "$name: das Artefakt ist abgelaufen. Workflow neu starten (Actions → agent-ci → Run workflow)."
      continue
    fi
    local tmp
    tmp="$(mktemp -d)"
    say "$name herunterladen"
    if ! curl -sSL --config "$konf" \
         "https://api.github.com/repos/$slug/actions/artifacts/$id/zip" -o "$tmp/paket.zip"; then
      rm -rf "$tmp"; warn "$name: Download gescheitert."; continue
    fi
    unzip -qo "$tmp/paket.zip" -d "$tmp/inhalt"
    # Mit dem Stand im Namen: auf dem Server liegen sonst zwei Dateien, die
    # gleich heissen und verschieden sind — und niemand weiss, welche der
    # Kunde bekommen hat.
    local datei
    while IFS= read -r datei; do
      local basis endung neu
      basis="$(basename "$datei")"
      endung="${basis##*.}"
      neu="${basis%.*}-$sha.$endung"
      install -m 0644 "$datei" "$ziel/$neu"
      printf '    %s (%s)\n' "$neu" "$(du -h "$datei" | cut -f1)"
      geholt=$((geholt + 1))
    done < <(find "$tmp/inhalt" -type f \( -name '*.msi' -o -name '*.deb' -o -name '*.exe' \))
    rm -rf "$tmp"
  done

  [ "$geholt" -gt 0 ] || die "Nichts geholt."
  say "$geholt Paket(e) in $ziel — die Konsole zeigt sie sofort"
}

# --- Bauen ------------------------------------------------------------------
cmd_bauen() {
  local ziel
  ziel="$(ziel_verzeichnis)"

  say "Debian-Paket bauen"
  command -v dpkg-deb >/dev/null || die "dpkg-deb fehlt (apt-get install dpkg-dev)."
  local version
  version="$(grep -oP '^VERSION\s*=\s*"\K[^"]+' "$REPO/agent/connector_agent/cli.py" || echo "0.0.0")"
  local deb="$ziel/magister-connector_${version}_amd64.deb"
  "$REPO/agent/packaging/debian/build-deb.sh" "$deb"
  chmod 0644 "$deb"
  say "$(basename "$deb")"

  # Und die ehrliche Auskunft zum MSI, statt eines Platzhalters, den jemand
  # für ein Paket hält.
  cat <<'HINWEIS'

Kein MSI: der eingefrorene Agent darin entsteht nur unter Windows.
Zwei Wege dorthin:

  aus der CI          ./scripts/agentenpakete.sh holen
  selbst gebaut       auf einer Windows-Maschine (nicht dem DC):
                        cd agent
                        .\packaging\windows\build-payload.ps1
                      dann das erzeugte ZIP hierher bringen und
                        ./scripts/agentenpakete.sh msi magister-connector-payload.zip

Nur die WiX-Quelle prüfen, ohne Windows in der Nähe:
  agent/packaging/windows/build-msi.sh --stub
Das Ergebnis heisst STUB und ist zum Installieren nicht gedacht.
HINWEIS
}

# --- MSI aus einem Windows-Payload -------------------------------------------
#: Die Anleitung für den Teil, den diese Maschine nicht tun kann. Sie steht
#: hier und nicht nur im Runbook, weil sie genau dann gebraucht wird, wenn
#: jemand `msi` ohne Payload aufruft — und weil die PowerShell-Zeilen in
#: einer Linux-Shell nichts als Fehlermeldungen ergeben.
payload_anleitung() {
  cat >&2 <<'ANLEITUNG'

Das Payload (der eingefrorene Agent) entsteht NUR unter Windows — PyInstaller
kann nicht für eine fremde Plattform bauen. Diese Maschine baut nur das MSI
darum herum.

  SCHRITT 1 — auf einer WINDOWS-Maschine mit Netz (nicht auf einem
  Domaincontroller; das Skript lädt Abhängigkeiten). In PowerShell:

      git clone https://github.com/Vita-Brevis-GmbH/magister.git
      cd magister\agent
      git checkout claude/multitenant-capability-planning-t6mygz
      .\packaging\windows\build-payload.ps1

  Ergebnis: magister-connector-payload.zip (rund 30 MiB).

  SCHRITT 2 — die Datei hierher bringen (scp, Share, USB) und dann HIER:

      ./scripts/agentenpakete.sh msi magister-connector-payload.zip

Ohne Windows in der Nähe bleibt der Weg über die CI: `holen`. Er setzt
voraus, dass agent-ci.yml auf `main` liegt und gelaufen ist.
ANLEITUNG
}

cmd_msi() {
  local quelle="${1:-}"
  if [ -z "$quelle" ]; then
    printf '\033[31m !! Kein Payload angegeben.\033[0m\n' >&2
    payload_anleitung
    exit 1
  fi
  if [ ! -e "$quelle" ]; then
    printf '\033[31m !! %s gibt es auf dieser Maschine nicht.\033[0m\n' "$quelle" >&2
    payload_anleitung
    exit 1
  fi
  for werkzeug in wixl wixl-heat msiinfo; do
    command -v "$werkzeug" >/dev/null \
      || die "$werkzeug fehlt: apt-get install -y wixl msitools"
  done

  local ziel payload aufraeumen=""
  ziel="$(ziel_verzeichnis)"
  if [ -d "$quelle" ]; then
    payload="$quelle"
  else
    command -v unzip >/dev/null || die "unzip fehlt (apt-get install unzip)."
    aufraeumen="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '$aufraeumen'" EXIT
    say "Payload entpacken"
    unzip -qo "$quelle" -d "$aufraeumen"
    # Ein ZIP aus `Compress-Archive -Path dist\*` hat die Dateien oben; eines
    # aus einem Artefakt kann einen Ordner davor haben. Beides annehmen,
    # statt den Bediener raten zu lassen, wie er hätte packen sollen.
    if [ -f "$aufraeumen/magister-connector.exe" ]; then
      payload="$aufraeumen"
    else
      payload="$(dirname "$(find "$aufraeumen" -name magister-connector.exe -type f | head -1)")"
      [ -n "$payload" ] && [ -d "$payload" ] \
        || die "In $quelle steckt kein magister-connector.exe."
    fi
  fi

  local version
  version="$(grep -oP '^VERSION\s*=\s*"\K[^"]+' "$REPO/agent/connector_agent/cli.py" || echo "0.0.0")"
  local out="$ziel/magister-connector-${version}-x64.msi"
  say "MSI bauen aus $payload"
  # Die .exe-Dateien kommen aus einem ZIP ohne Ausführungsrecht; wixl stört
  # das nicht, aber ein späterer Handgriff auf dem Payload schon.
  chmod +x "$payload"/*.exe 2>/dev/null || true
  "$REPO/agent/packaging/windows/build-msi.sh" "$payload" "$out"
  chmod 0644 "$out"
  say "$(basename "$out") liegt in $ziel — die Konsole zeigt es sofort"
}

# --- Zeigen -----------------------------------------------------------------
cmd_zeigen() {
  local ziel
  ziel="$(ziel_verzeichnis)"
  say "Paketverzeichnis: $ziel"
  local leer=1
  while IFS= read -r datei; do
    leer=0
    printf '  %-52s %8s  %s\n' "$(basename "$datei")" \
      "$(du -h "$datei" | cut -f1)" "$(sha256sum "$datei" | cut -c1-16)…"
  done < <(find "$ziel" -maxdepth 1 -type f \( -name '*.msi' -o -name '*.deb' -o -name '*.exe' -o -name '*.zip' \) | sort)
  [ "$leer" -eq 0 ] || warn "Leer — 'holen' oder 'bauen'."
}

BEFEHL="${1:-zeigen}"; shift || true
case "$BEFEHL" in
  holen)  cmd_holen "$@" ;;
  bauen)  cmd_bauen "$@" ;;
  msi)    cmd_msi "$@" ;;
  zeigen) cmd_zeigen "$@" ;;
  *) die "Unbekannter Befehl: $BEFEHL (holen, bauen, msi, zeigen)" ;;
esac
