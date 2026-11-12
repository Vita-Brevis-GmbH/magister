#!/usr/bin/env python3
"""Zustand des Plattform-Hosts, als JSON für die Konsole (ADR-0024, Überwachung).

Läuft auf dem Host, als root, aus dem Ops-Agenten heraus (höchstens einmal je
Minute) und schreibt ``$OPS_DIR/health.json``. Die Konsole liest die Datei nur;
sie selbst hat keinen Zugang zu Docker und zu den Ports des Hosts, und das
bleibt so. Eine übernommene Konsole erfährt aus dieser Datei, was sie über
die Seite „Plattform" ohnehin sieht — und kann nichts daran ändern.

Erhoben wird, was beim Betrieb auf dem Dev-Host wirklich schiefging:

* **Dienste**: jeder Container beider Stacks — läuft er, ist er gesund?
* **Ports**: wer lauscht auf 80, 443, 4444, 46200? Ein Container dieses
  Stacks oder etwas anderes (der Caddy aus dem Debian-Paket auf :80)?
* **Proben**: echte Anfragen durch Caddy — Umleitung auf 80, Kundenportal
  auf 443, Konsole auf 4444, Connector-Kanal auf 46200, und je Kunde, ob er
  bedient wird (401 ohne Anmeldung) oder in Wartung steht (503).
* **Zertifikate**: Restlaufzeit der Serverzertifikate.
* **Platte**: Belegung.

Nur Standardbibliothek: auf dem Host gibt es python3, aber kein venv.
Keine Geheimnisse in der Ausgabe — Namen, Zustände, Zahlen.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

#: Dieselben Projektnamen wie in plattform-aufbau.sh.
STACKS = {"konsole": "deploy", "daten": "magister"}

#: Die Ports und wem sie gehören sollen.
PORTS = {
    80: "Kundenportal (Umleitung auf HTTPS)",
    443: "Kundenportal (HTTPS)",
    4444: "Konsole (Verwaltung)",
    46200: "Connector-Kanal",
}

#: Ein Hostname, wie die Konsole ihn prüft. Alles andere wird nicht geprobt —
#: die Zielliste kommt aus der Konsole, und die Konsole könnte übernommen sein.
HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
SLUG = re.compile(r"^[a-z][a-z0-9_]{1,30}$")

TIMEOUT = 8


def _run(cmd: list[str], timeout: int = TIMEOUT) -> tuple[int, str]:
    try:
        # Feste Befehle; einzige variable Teile sind Ports, Pfade und
        # Hostnamen, die vorher gegen ein Muster geprüft sind.
        done = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, type(exc).__name__
    return done.returncode, done.stdout


def konf(plattform: Path) -> dict[str, str]:
    """PLATTFORM_DOMAIN und PLATTFORM_BIND aus plattform.conf."""
    werte = {"PLATTFORM_DOMAIN": "dev-mgmt.int.vitabrevis.ch", "PLATTFORM_BIND": "127.0.0.1"}
    datei = plattform / "plattform.conf"
    if datei.is_file():
        for zeile in datei.read_text(encoding="utf-8").splitlines():
            if "=" in zeile and not zeile.lstrip().startswith("#"):
                name, _, wert = zeile.partition("=")
                werte[name.strip()] = wert.strip()
    return werte


def services() -> list[dict[str, Any]]:
    """Jeder Container beider Stacks, auch die angehaltenen."""
    out: list[dict[str, Any]] = []
    for stack, project in STACKS.items():
        code, text = _run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                '{{.Label "com.docker.compose.service"}}\t{{.State}}\t{{.Status}}\t{{.Names}}',
            ]
        )
        if code != 0:
            out.append(
                {"stack": stack, "service": "?", "ok": False, "state": "docker nicht abfragbar"}
            )
            continue
        for zeile in text.splitlines():
            teile = zeile.split("\t")
            if len(teile) != 4:
                continue
            service, state, status, name = teile
            healthy = "(healthy)" in status
            unhealthy = "(unhealthy)" in status or "(health: starting)" in status
            # Einmal-Container (z. B. backup-pruefer via `run --rm`) tauchen
            # hier nicht auf; ein beendeter Dienst-Container ist ein Befund.
            out.append(
                {
                    "stack": stack,
                    "service": service,
                    "container": name,
                    "state": state,
                    "status": status,
                    "ok": state == "running" and not unhealthy,
                    "healthy": healthy,
                }
            )
    return out


def ports() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for port, zweck in PORTS.items():
        code, text = _run(["ss", "-ltnpH", f"sport = :{port}"])
        prozesse = sorted(set(re.findall(r'\(\("([^"]+)"', text))) if code == 0 else []
        lauscht = code == 0 and bool(text.strip())
        if not lauscht:
            # Ohne Userland-Proxy veröffentlicht Docker Ports nur per iptables;
            # dann lauscht für `ss` niemand, obwohl der Port antwortet.
            dcode, dtext = _run(["docker", "ps", "--filter", f"publish={port}", "-q"])
            if dcode == 0 and dtext.strip():
                lauscht, prozesse, code = True, ["docker"], 0
        # Docker veröffentlicht über docker-proxy (oder direkt per iptables,
        # dann ohne Prozess). Alles andere ist ein fremder Dienst.
        fremd = [p for p in prozesse if p not in ("docker-proxy", "dockerd", "docker")]
        if code == 127:
            detail = "ss nicht verfügbar — Belegung unbekannt"
        elif fremd:
            detail = f"belegt von {', '.join(fremd)} — nicht dieser Stack"
        elif not lauscht:
            detail = "niemand lauscht"
        else:
            detail = ""
        out.append(
            {
                "port": port,
                "purpose": zweck,
                "listening": lauscht,
                "by": prozesse,
                "ok": lauscht and not fremd,
                "detail": detail,
            }
        )
    return out


def _curl(url: str, *, resolve: str, timeout: int = TIMEOUT) -> tuple[str, str]:
    """HTTP-Code (oder '000') und curls Fehlermeldung."""
    code, text = _run(
        [
            "curl",
            "-sS",
            "-k",
            "--noproxy",
            "*",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            str(timeout),
            "--resolve",
            resolve,
            url,
        ],
        timeout=timeout + 2,
    )
    return (text.strip() or "000"), ("" if code == 0 else f"curl {code}")


def probes(domain: str, bind: str, ziele: list[dict[str, str]]) -> list[dict[str, Any]]:
    konsole = f"konsole.{domain}"
    connect = f"connect.{domain}"
    out: list[dict[str, Any]] = []

    def probe(
        name: str, url: str, resolve: str, erwartet: set[str], bedeutung: dict[str, str]
    ) -> None:
        http, fehler = _curl(url, resolve=resolve)
        out.append(
            {
                "name": name,
                "ok": http in erwartet,
                "http": http,
                "detail": bedeutung.get(http, fehler or f"HTTP {http}"),
            }
        )

    probe(
        "Port 80 leitet auf HTTPS um",
        f"http://{konsole}/",
        f"{konsole}:80:127.0.0.1",
        {"301", "308"},
        {"000": "keine Antwort — lauscht Caddy der Datenebene auf 80?"},
    )
    probe(
        "Kundenportal antwortet (443, /healthz)",
        f"https://{konsole}/healthz",
        f"{konsole}:443:127.0.0.1",
        {"200"},
        {"200": "Datenebene antwortet", "502": "Caddy läuft, die Datenebene nicht"},
    )
    probe(
        "Konsole antwortet (4444)",
        f"https://{konsole}:4444/api/health",
        f"{konsole}:4444:{bind}",
        {"200", "401", "403", "404"},
        {"000": "keine Antwort auf der Verwaltungsadresse"},
    )
    probe(
        "Connector-Kanal antwortet (46200)",
        f"https://{connect}:46200/connector/jobs",
        f"{connect}:46200:127.0.0.1",
        # Ohne Agentenzertifikat ist 401/404 die richtige Antwort: der Kanal
        # steht, er lässt nur niemanden ohne Nachweis herein.
        {"401", "403", "404"},
        {"000": "keine Antwort — Port 46200 oder Caddy der Konsole"},
    )
    for ziel in ziele:
        host, slug = ziel.get("hostname", ""), ziel.get("slug", "")
        if not HOSTNAME.match(host) or not SLUG.match(slug):
            continue
        probe(
            f"Kunde {slug} ({host})",
            f"https://{host}/api/me/modules",
            f"{host}:443:127.0.0.1",
            # 401: der Kunde ist aufgelöst, bedienbar, will nur eine Anmeldung.
            {"401"},
            {
                "401": "bedient",
                "503": "Wartung — Kundenschlüssel, Schemastand oder Konsole (Kunde anbinden?)",
                "404": "der Datenebene unbekannt — Kunde anbinden",
                "502": "Caddy läuft, die Datenebene nicht",
                "000": "keine Antwort auf 443",
            },
        )
    return out


def certificates(certs: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    now = dt.datetime.now(dt.UTC)
    for name, zweck in (
        ("tenants.pem", "Kundenportale"),
        ("console.pem", "Konsole"),
        ("connector.pem", "Connector-Kanal"),
    ):
        datei = certs / name
        if not datei.is_file():
            continue
        code, text = _run(["openssl", "x509", "-enddate", "-noout", "-in", str(datei)])
        if code != 0 or "=" not in text:
            out.append({"name": name, "purpose": zweck, "ok": False, "detail": "nicht lesbar"})
            continue
        ende = dt.datetime.strptime(text.strip().split("=", 1)[1], "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=dt.UTC
        )
        tage = (ende - now).days
        out.append(
            {
                "name": name,
                "purpose": zweck,
                "not_after": ende.isoformat(),
                "days_left": tage,
                "ok": tage > 21,
            }
        )
    return out


def disk(plattform: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pfad in sorted({Path("/"), plattform, Path("/var/lib/docker")}, key=str):
        if not pfad.exists():
            continue
        belegt = shutil.disk_usage(pfad)
        prozent = round(100 * belegt.used / belegt.total) if belegt.total else 0
        out.append({"path": str(pfad), "used_pct": prozent, "ok": prozent < 90})
    return out


def zustand(plattform: Path, ops: Path) -> dict[str, Any]:
    werte = konf(plattform)
    try:
        ziele_raw: object = json.loads((ops / "probe-targets.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ziele_raw = []
    ziele = [
        {str(k): str(v) for k, v in z.items()}
        for z in (ziele_raw if isinstance(ziele_raw, list) else [])
        if isinstance(z, dict)
    ][:200]
    bericht: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "services": services(),
        "ports": ports(),
        "probes": probes(werte["PLATTFORM_DOMAIN"], werte["PLATTFORM_BIND"], ziele),
        "certificates": certificates(plattform / "certs"),
        "disk": disk(plattform),
    }
    teile = ("services", "ports", "probes", "certificates", "disk")
    bericht["ok"] = all(e.get("ok", False) for t in teile for e in bericht[t])
    return bericht


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--ops", required=True, help="Austauschverzeichnis (OPS_DIR)")
    parser.add_argument("--plattform", help="Plattform-Verzeichnis (Vorgabe: das über --ops)")
    args = parser.parse_args(argv)
    ops = Path(args.ops)
    plattform = Path(args.plattform) if args.plattform else ops.parent
    bericht = zustand(plattform, ops)
    ziel = ops / "health.json"
    tmp = ops / ".health.json.tmp"
    tmp.write_text(json.dumps(bericht, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ziel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
