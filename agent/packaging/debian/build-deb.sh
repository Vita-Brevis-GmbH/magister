#!/usr/bin/env bash
# Baut das .deb für Debian/Ubuntu (ADR-0014).
#
#     ./build-deb.sh [ausgabe.deb]
#
# **Warum ein venv unter /opt und keine python3-*-Abhängigkeiten.** Der Agent
# braucht `magister_api` (nicht in Debian), httpx und cryptography in Fassungen,
# die Debian nicht überall führt, und unter Windows liefern wir aus demselben
# Grund ein eingefrorenes Bündel. Ein venv ist der Weg, der auf allen
# unterstützten Ubuntu- und Debian-Ständen dasselbe ergibt — und der einzige,
# bei dem eine Aktualisierung der Distribution die Abhängigkeiten des Agenten
# nicht verschiebt.
#
# Der Preis: das Paket ist grösser und Sicherheitsaktualisierungen an httpx
# oder cryptography kommen über ein neues Paket von uns und nicht über
# `apt upgrade`. Das ist bewusst so entschieden und gehört in den Betrieb —
# derselbe Handel wie beim MSI.
#
# Gebaut wird mit **python3.12**, weil der Agent es verlangt. Läuft das Skript
# auf einem System mit älterem Vorgabe-Python, wird 3.12 ausdrücklich gesucht.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_ROOT="$(cd "$HERE/../.." && pwd)"
REPO_ROOT="$(cd "$AGENT_ROOT/.." && pwd)"

VERSION="${MAGISTER_AGENT_VERSION:-}"
if [[ -z "$VERSION" ]]; then
    VERSION=$(grep -oP '^VERSION\s*=\s*"\K[^"]+' "$AGENT_ROOT/connector_agent/cli.py")
fi
ARCH="$(dpkg --print-architecture)"
OUT="${1:-$HERE/magister-connector_${VERSION}_${ARCH}.deb}"

for tool in dpkg-deb dpkg; do
    command -v "$tool" >/dev/null || { echo "$tool fehlt." >&2; exit 2; }
done

PY=""
for candidate in python3.12 python3.13 python3; do
    if command -v "$candidate" >/dev/null; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
            PY="$candidate"
            break
        fi
    fi
done
if [[ -z "$PY" ]]; then
    echo "Kein Python >= 3.12 gefunden. Der Agent verlangt es." >&2
    exit 2
fi
echo "Python: $("$PY" --version)"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

VENV="$STAGE/opt/magister-connector"
mkdir -p "$VENV" "$STAGE/DEBIAN" "$STAGE/usr/bin" \
         "$STAGE/lib/systemd/system" "$STAGE/etc/magister-connector" \
         "$STAGE/usr/share/doc/magister-connector"

# --- venv mit dem Agenten -------------------------------------------------
"$PY" -m venv "$VENV"
# Ohne pip im Ergebnis: es wird nach der Installation nicht gebraucht und
# spart 10 MB. `--no-compile` NICHT, denn .pyc sparen beim Start Zeit und der
# Dienst startet in einem Verzeichnis, in das er nicht schreiben darf.
"$VENV/bin/pip" install --quiet --upgrade pip setuptools wheel
echo "Abhängigkeiten werden installiert (das dauert)…"
"$VENV/bin/pip" install --quiet "$REPO_ROOT/apps/api"
"$VENV/bin/pip" install --quiet --no-deps "$AGENT_ROOT"
"$VENV/bin/pip" install --quiet httpx cryptography
"$VENV/bin/pip" uninstall --quiet --yes pip setuptools wheel || true

# Die Shebangs der Konsolenskripte zeigen auf den Bauort. Das venv landet aber
# unter /opt/magister-connector — ohne diese Zeile startet nach der
# Installation nichts, und die Fehlermeldung ist "bad interpreter: No such
# file or directory", was in die falsche Richtung zeigt.
for script in "$VENV"/bin/*; do
    [[ -f "$script" ]] || continue
    head -c2 "$script" 2>/dev/null | grep -q '#!' || continue
    sed -i "1s|^#!.*python.*|#!/opt/magister-connector/bin/python3|" "$script"
done
# pyvenv.cfg zeigt auf das System-Python; der Pfad des venv selbst steht darin
# nicht, also bleibt es gültig. Die Symlinks in bin/ sind absolut auf
# /usr/bin/python3.x — auch gültig.
"$VENV/bin/python3" -c "import connector_agent, magister_api; print('venv ok')" \
    || { echo "Das venv ist unbrauchbar." >&2; exit 1; }

# --- Dateien --------------------------------------------------------------
cat > "$STAGE/usr/bin/magister-connector" <<'WRAP'
#!/bin/sh
# Aufruf über das venv des Pakets. Kein Symlink auf bin/magister-connector,
# damit ein `--config`-Vorgabewert aus dem Paket gilt und nicht der des
# Arbeitsverzeichnisses.
exec /opt/magister-connector/bin/python3 -m connector_agent.cli \
    --config "${MAGISTER_CONNECTOR_CONFIG:-/etc/magister-connector/config.json}" "$@"
WRAP
chmod 0755 "$STAGE/usr/bin/magister-connector"

install -m 0644 "$AGENT_ROOT/deploy/magister-connector.service" \
        "$STAGE/lib/systemd/system/magister-connector.service"
install -m 0644 "$AGENT_ROOT/deploy/config.example.json" \
        "$STAGE/etc/magister-connector/config.example.json"
install -m 0644 "$AGENT_ROOT/deploy/ad.env.example" \
        "$STAGE/etc/magister-connector/ad.env.example"
install -m 0644 "$AGENT_ROOT/README.md" \
        "$STAGE/usr/share/doc/magister-connector/README.md"
install -m 0644 "$HERE/../windows/INSTALL.txt" \
        "$STAGE/usr/share/doc/magister-connector/INSTALL-hintergrund.txt"

# --- DEBIAN ---------------------------------------------------------------
sed -e "s|@VERSION@|$VERSION|" -e "s|@ARCH@|$ARCH|" "$HERE/control.in" \
    > "$STAGE/DEBIAN/control"
install -m 0755 "$HERE/postinst" "$STAGE/DEBIAN/postinst"
install -m 0755 "$HERE/prerm" "$STAGE/DEBIAN/prerm"
install -m 0755 "$HERE/postrm" "$STAGE/DEBIAN/postrm"
# conffiles: die Vorlagen dürfen bei einem Update ersetzt werden, eine vom
# Betreiber angelegte config.json gehört NICHT dazu — sie ist kein Teil des
# Pakets, und genau deshalb überschreibt ein Update sie nie.
cat > "$STAGE/DEBIAN/conffiles" <<'CONF'
/etc/magister-connector/config.example.json
/etc/magister-connector/ad.env.example
CONF

# Grösse für die Paketverwaltung.
size_kb=$(du -sk "$STAGE" | cut -f1)
echo "Installed-Size: $size_kb" >> "$STAGE/DEBIAN/control"

dpkg-deb --root-owner-group --build "$STAGE" "$OUT" >/dev/null
echo "Paket: $OUT ($(du -h "$OUT" | cut -f1))"

# --- nachsehen, ob drinsteht, was drinstehen soll -------------------------
#
# Der Inhalt wird EINMAL in eine Datei gelesen und danach dort gesucht. Mit
# `dpkg-deb --contents | grep -q` bricht grep beim ersten Treffer ab, dpkg-deb
# bekommt SIGPIPE und meldet "tar subprocess was killed by signal (Broken
# pipe)" — und die folgenden Prüfungen sehen dann eine abgeschnittene Liste
# und melden Dateien als fehlend, die drin sind.
LISTING="$STAGE/contents.txt"
dpkg-deb --contents "$OUT" > "$LISTING"
echo "Inhalt: $(grep -c '' "$LISTING") Einträge"

missing=0
for path in \
    ./opt/magister-connector/bin/python3 \
    ./usr/bin/magister-connector \
    ./lib/systemd/system/magister-connector.service \
    ./etc/magister-connector/config.example.json
do
    if ! grep -qE " ${path}( ->|\$)" "$LISTING"; then
        echo "FEHLER: $path fehlt im Paket." >&2
        missing=1
    fi
done
# Das Zustandsverzeichnis darf NICHT im Paket sein: es wird im postinst mit
# 0700 und dem richtigen Eigentümer angelegt. Läge es im Paket, hätte es die
# Rechte aus dem Bauverzeichnis.
if grep -q "/var/lib/magister-connector" "$LISTING"; then
    echo "FEHLER: /var/lib/magister-connector liegt im Paket." >&2
    echo "Es gehört ins postinst, sonst trägt es die Rechte des Bauorts." >&2
    missing=1
fi
# Und keine Geheimnisse: eine echte config.json oder ein Schlüssel im Paket
# wäre ein Leck in jedem Spiegel, der es weiterverteilt.
if grep -qE "(agent-key\.pem|secrets\.json|/etc/magister-connector/config\.json$|/etc/magister-connector/ad\.env$)" "$LISTING"; then
    echo "FEHLER: das Paket enthält eine echte Konfiguration oder ein Geheimnis." >&2
    missing=1
fi
[[ $missing -eq 0 ]] || exit 1
echo "Prüfung: Inhalt vollständig, keine Geheimnisse, kein Zustandsverzeichnis."
