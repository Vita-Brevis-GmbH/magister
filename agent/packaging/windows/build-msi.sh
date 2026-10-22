#!/usr/bin/env bash
# Baut das MSI aus einem fertigen Payload-Verzeichnis (ADR-0014).
#
#     ./build-msi.sh <payload-verzeichnis> [ausgabe.msi]
#
# **Die Arbeitsteilung, und warum sie so ist:** das Payload — der eingefrorene
# Agent samt Python-Laufzeit — muss unter Windows gebaut werden, weil
# PyInstaller keine fremden Plattformen bauen kann. Das MSI **darum herum**
# baut dieses Skript unter Linux mit `wixl` (msitools). Zwei Vorteile: der
# Paketbau läuft auf derselben Maschine wie alles andere, und die WiX-Quelle
# ist auf dem Entwicklerrechner prüfbar — mit einem Platzhalter-Payload
# (`--stub`) sogar ohne Windows in der Nähe.
#
# Im Payload-Verzeichnis erwartet werden:
#   magister-connector.exe          — die Kommandozeile (enroll, run, check)
#   magister-connector-service.exe  — der Dienst-Einsprungpunkt
#   config.example.json             — Konfigurationsvorlage
#   INSTALL.txt                     — Anleitung für den Kunden
#   ... plus alles, was PyInstaller dazulegt
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="${MAGISTER_AGENT_VERSION:-}"

stub=0
if [[ "${1:-}" == "--stub" ]]; then
    stub=1
    shift
fi

if [[ $stub -eq 1 ]]; then
    # Platzhalter-Payload: prüft die WiX-Quelle, den Tabellenaufbau und die
    # Dienst-Einträge, ohne dass ein Windows-Build vorliegen muss. Das
    # Ergebnis ist ein installierbares MSI mit unbrauchbarem Inhalt — deshalb
    # trägt es das im Namen.
    PAYLOAD="$(mktemp -d)"
    trap 'rm -rf "$PAYLOAD"' EXIT
    for name in magister-connector.exe magister-connector-service.exe; do
        printf 'PLATZHALTER — kein echtes Programm\n' > "$PAYLOAD/$name"
    done
    cp "$HERE/../../deploy/config.example.json" "$PAYLOAD/config.example.json"
    cp "$HERE/INSTALL.txt" "$PAYLOAD/INSTALL.txt"
    printf 'PLATZHALTER\n' > "$PAYLOAD/python312.dll"
    mkdir -p "$PAYLOAD/lib"
    printf 'PLATZHALTER\n' > "$PAYLOAD/lib/beispiel.pyd"
    OUT="${1:-$HERE/magister-connector-STUB.msi}"
else
    PAYLOAD="${1:?Payload-Verzeichnis angeben (oder --stub)}"
    OUT="${2:-$HERE/magister-connector-${VERSION:-0.0.0}-x64.msi}"
fi

# Absolut machen: weiter unten läuft `msibuild` im Arbeitsverzeichnis. Mit
# einem relativen Pfad (so ruft die CI das Skript auf) schrieb es dort in eine
# neue, leere Datei, und dem eigentlichen MSI fehlte der PATH-Eintrag. Die
# Prüfung unten hat es gefunden, der Stub-Bau mit absolutem Pfad nicht.
OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"

if [[ ! -d "$PAYLOAD" ]]; then
    echo "Payload-Verzeichnis $PAYLOAD fehlt." >&2
    exit 2
fi

# Version aus dem Agenten, wenn nicht vorgegeben. Eine MSI-Version hat drei
# Zahlen; alles darüber hinaus (Vorabkennungen wie "0.1.0rc1") wirft Windows
# ohnehin weg, deshalb wird hier abgeschnitten und nicht geraten.
if [[ -z "$VERSION" ]]; then
    VERSION=$(grep -oP '^BASE_VERSION\s*=\s*"\K[^"]+' "$HERE/../../connector_agent/cli.py" || true)
fi
VERSION="${VERSION:-0.0.0}"
MSI_VERSION=$(echo "$VERSION" | grep -oE '^[0-9]+(\.[0-9]+){0,2}' || echo "0.0.0")
if [[ "$VERSION" != "$MSI_VERSION" ]]; then
    echo "Hinweis: Agent-Version '$VERSION' wird im MSI zu '$MSI_VERSION' (Windows nimmt nur x.y.z)."
fi

for tool in wixl wixl-heat msibuild msiinfo; do
    if ! command -v "$tool" >/dev/null; then
        echo "$tool fehlt. Auf Debian/Ubuntu: apt-get install wixl" >&2
        exit 2
    fi
done

for required in magister-connector.exe magister-connector-service.exe config.example.json INSTALL.txt; do
    if [[ ! -f "$PAYLOAD/$required" ]]; then
        echo "Im Payload fehlt $required." >&2
        exit 2
    fi
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Die Dateiliste wird erzeugt und nicht gepflegt: PyInstaller legt rund
# hundert Dateien ab, und eine handgepflegte Liste in der WiX-Quelle wäre
# beim ersten Abhängigkeitswechsel falsch.
#
# Ausgenommen sind die Dateien, die eigene Komponenten haben — der Dienst
# (wegen ServiceInstall) und die beiden Dateien, die ins
# Zustandsverzeichnis gehören. Zweimal installiert wäre ein
# ICE-Fehler und zur Laufzeit ein Rätsel.
#
# Die Pfade gehen RELATIV hinein (deshalb das `cd` und `--prefix ""`): mit
# absoluten Pfaden baut wixl-heat den ganzen Verzeichnisbaum von / an als
# MSI-Verzeichnisse nach, und die Dateien landen unter
# "Programme\Magister Connector\tmp\tmp.XYZ\".
#
# Das `Name="."` im Ergebnis ist richtig und kein Fehler: im MSI-Directory-
# Table heisst DefaultDir "." genau "dasselbe Verzeichnis wie das
# übergeordnete". WiX selbst schreibt es so.
( cd "$PAYLOAD" && find . -type f -printf '%P\n' | sort \
  | grep -v -x -e 'magister-connector-service.exe' -e 'config.example.json' \
  | wixl-heat --win64 \
      --directory-ref INSTALLDIR \
      --component-group Payload \
      --var var.PayloadDir \
      --prefix "" ) \
  > "$WORK/payload.wxs"

files=$(grep -c "<File" "$WORK/payload.wxs" || true)
echo "Payload: $files Datei(en) aus $PAYLOAD"

cp "$HERE/magister-connector.wxs" "$WORK/"
# Win64=yes, weil wixl-heat `Win64="$(var.Win64)"` in jede Komponente
# schreibt. Fehlt die Definition, bricht der Präprozessor mitten im Element
# ab — und die Fehlermeldung lautet dann "Couldn't find end of Start Tag
# Component", was in die falsche Richtung zeigt.
#
# wixl meldet unbekannte Attribute und Elemente nur als GLib-Warnung auf
# stderr und **baut trotzdem weiter**. Genau so verliert man ein Attribut wie
# `Permanent` oder ein ganzes `ServiceInstall`, ohne es zu merken — das MSI
# installiert dann Dateien und keinen Dienst, und auffallen tut es beim
# Kunden. Deshalb wird stderr mitgelesen und jede solche Meldung ist hier ein
# Abbruch.
if ! wixl -a x64 \
        -D "PayloadDir=$PAYLOAD" \
        -D "Version=$MSI_VERSION" \
        -D "Win64=yes" \
        -o "$OUT" \
        "$WORK/magister-connector.wxs" \
        "$WORK/payload.wxs" 2> "$WORK/wixl.err"; then
    cat "$WORK/wixl.err" >&2
    echo "wixl ist gescheitert." >&2
    exit 1
fi
if grep -qE "has no property named|unhandled child|CRITICAL|WARNING" "$WORK/wixl.err"; then
    cat "$WORK/wixl.err" >&2
    echo >&2
    echo "wixl hat Teile der WiX-Quelle stillschweigend verworfen (siehe oben)." >&2
    echo "Das Ergebnis wäre ein MSI, dem etwas fehlt. Abbruch." >&2
    exit 1
fi
[[ -s "$WORK/wixl.err" ]] && cat "$WORK/wixl.err" >&2

# Der Installationsordner kommt in den System-PATH, damit
# `magister-connector check` in JEDER Eingabeaufforderung geht und nicht nur
# in der aus dem Startmenü. Ohne das war der erste Befehl beim Kunden ein
# „nicht gefunden", und die Fehlersuche begann bei der falschen Frage.
#
# Nachträglich und nicht in der WiX-Quelle: wixl kennt das Element
# `Environment` nicht („unhandled child Component node Environment") und
# bricht ab. Die Tabelle selbst ist aber schlicht — vier Spalten — und
# Windows Installer liest sie, egal wer sie geschrieben hat. `msibuild`
# stammt aus denselben msitools wie wixl.
#
#   =-*PATH   = setzen beim Installieren, - zurücknehmen beim Deinstallieren,
#             * Systemvariable (nicht die des installierenden Benutzers)
#   [~];[INSTALLDIR]   anhängen, nicht ersetzen — und hinten, damit kein
#             Programm aus diesem Ordner eines aus System32 überdeckt
#
# Hängt an C.Registry: die Komponente wird immer installiert und hat keinen
# anderen Grund, sich zu ändern. Die Aktionen bekommen die Nummern, die auch
# WiX vergibt (3300 vor InstallFiles, 5200 nach WriteRegistryValues).
printf 'Environment\tName\tValue\tComponent_\r\ns72\tl255\tL255\ts72\r\nEnvironment\tEnvironment\r\n' \
    > "$WORK/Environment.idt"
printf 'E.Path\t=-*PATH\t[~];[INSTALLDIR]\tC.Registry\r\n' >> "$WORK/Environment.idt"
msiinfo export "$OUT" InstallExecuteSequence > "$WORK/InstallExecuteSequence.idt"
printf 'RemoveEnvironmentStrings\t\t3300\r\nWriteEnvironmentStrings\t\t5200\r\n' \
    >> "$WORK/InstallExecuteSequence.idt"
( cd "$WORK" && msibuild "$OUT" -i Environment.idt InstallExecuteSequence.idt )

echo "MSI: $OUT ($(du -h "$OUT" | cut -f1))"

# Nachsehen, ob wirklich drinsteht, was drinstehen soll. wixl meldet
# unbekannte Elemente nur auf stderr und baut trotzdem — ein MSI ohne
# ServiceInstall installiert Dateien und keinen Dienst, und das merkt man
# sonst erst beim Kunden.
missing=0
for table in ServiceInstall ServiceControl File Component Feature Registry; do
    if ! msiinfo tables "$OUT" | grep -qx "$table"; then
        echo "FEHLER: Tabelle $table fehlt im MSI." >&2
        missing=1
    fi
done
if ! msiinfo export "$OUT" ServiceInstall | grep -q MagisterConnector; then
    echo "FEHLER: der Dienst MagisterConnector steht nicht im MSI." >&2
    missing=1
fi
if ! msiinfo export "$OUT" Environment 2>/dev/null | grep -q $'=-\\*PATH\t\\[~\\];\\[INSTALLDIR\\]'; then
    echo "FEHLER: der PATH-Eintrag für den Installationsordner fehlt im MSI." >&2
    missing=1
fi
for action in WriteEnvironmentStrings RemoveEnvironmentStrings; do
    if ! msiinfo export "$OUT" InstallExecuteSequence | grep -q "^$action"; then
        echo "FEHLER: die Aktion $action fehlt — der PATH-Eintrag bliebe wirkungslos." >&2
        missing=1
    fi
done
[[ $missing -eq 0 ]] || exit 1
echo "Prüfung: Dienst, Tabellen und PATH-Eintrag vorhanden."

# Und jetzt das, was `msiinfo` NICHT sieht: ob Windows die Datei überhaupt
# öffnet. `msiinfo` benutzt dieselbe Bibliothek, die das MSI geschrieben hat,
# und liest deshalb auch eine Datenbank anstandslos, die sich selbst
# widerspricht. Genau so ist ein Paket bis auf den Domaincontroller gekommen,
# das Windows mit Fehler 1620 abgewiesen hat (msi_pruefen.py erklärt den Fall).
"$HERE/msi_pruefen.py" "$OUT"
