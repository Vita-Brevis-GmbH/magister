#!/usr/bin/env bash
# Nach einem Neustart des Hosts muss jeder Dienst von selbst wiederkommen:
# jeder Dienst in den Compose-Dateien der Plattform braucht eine
# `restart:`-Zeile. Die Konsole hatte keine — nach dem nächtlichen Patchen
# blieb sie aus, und die Datenebene kannte keinen Kunden mehr.
set -euo pipefail
cd "$(dirname "$0")/../.."

python3 - <<'PY'
import re, sys

# Basisdateien: dort stehen die Dienste. Overrides erben die Policy.
FILES = ["cockpit/deploy/docker-compose.yml", "deploy/compose/docker-compose.yml"]
fehler = []
for path in FILES:
    lines = open(path, encoding="utf-8").read().splitlines()
    in_services = False
    current = None
    has_restart: dict[str, bool] = {}
    for line in lines:
        if re.match(r"^services:\s*$", line):
            in_services = True
            continue
        if in_services and re.match(r"^\S", line):
            in_services = False
        if not in_services:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            current = m.group(1)
            has_restart[current] = False
            continue
        if current and re.match(r"^    restart:\s*\S", line):
            has_restart[current] = True
    if not has_restart:
        fehler.append(f"{path}: keine Dienste gefunden")
    for name, ok in has_restart.items():
        if not ok:
            fehler.append(f"{path}: Dienst '{name}' ohne restart:")
if fehler:
    print("\n".join(fehler))
    sys.exit(1)
print("ok: jeder Dienst hat eine restart-Policy")
PY
