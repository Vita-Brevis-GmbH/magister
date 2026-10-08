"""``magister-connector update`` — die neueste Fassung von der Plattform holen und einspielen.

Ein Befehl statt Herunterladen, Kopieren, Installieren, Dienst starten:

1. Die Plattform fragen, welche Fassung bereitliegt (``GET /connector/update``),
   über den beglaubigten Kanal — Client-Zertifikat und API-Key, wie jeder
   Auftrag. Dieselbe Datei, die das Cockpit unter „Agent herunterladen“ zeigt.
2. Nur wenn sie neuer ist als die laufende: das MSI ins Zustandsverzeichnis
   laden (nur SYSTEM und Administratoren) und die SHA-256 prüfen.
3. Ein abgekoppeltes Skript startet ``msiexec`` still und danach den Dienst.
   Abgekoppelt, weil dieses Programm aus dem Ordner läuft, den das MSI ersetzt.

**Der Agent aktualisiert sich nie von selbst.** Er läuft auf dem DC als
LocalSystem; ein Update, das die Plattform auslösen könnte, gäbe einer
übernommenen Plattform Code auf Tier 0. Auslösen tut es ein Mensch mit
Administratorrechten auf dem DC — genau wie beim Download von Hand.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

from connector_agent.config import IS_WINDOWS, AgentConfig, AgentSecrets
from connector_agent.tls import build_context

#: Obergrenze eines MSI. Das Paket hat rund 30 MiB; alles weit darüber ist
#: kein Agent.
MAX_BYTES = 200 * 1024 * 1024

#: Name des Dienstes (wie in der .wxs).
SERVICE = "MagisterConnector"

_DATEINAME = re.compile(r"^magister-connector-\d+\.\d+\.\d+-x64(?:-[0-9a-f]{6,40})?\.msi$")


class UpdateError(RuntimeError):
    """Das Update ging nicht. Die Meldung sagt, warum und was zu tun ist."""


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    filename: str
    version: str
    sha256: str
    size_bytes: int


def parse_version(text: str) -> tuple[int, int, int] | None:
    """``0.2.190`` oder ``0.2.190 (abc1234)`` → (0, 2, 190)."""
    match = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)", text or "")
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def is_newer(available: str, running: str) -> bool:
    new, old = parse_version(available), parse_version(running)
    return new is not None and (old is None or new > old)


def _client(
    config: AgentConfig,
    secrets: AgentSecrets,
    *,
    agent_version: str,
    transport: httpx.BaseTransport | None,
) -> httpx.Client:
    return httpx.Client(
        base_url=config.endpoint,
        timeout=httpx.Timeout(30.0, read=300.0),
        verify=build_context(
            ca_bundle=config.ca_bundle, cert=config.cert_path, key=config.key_path
        ),
        trust_env=False,
        proxy=config.proxy,
        transport=transport,
        headers={
            "X-Connector-Api-Key": secrets.api_key,
            "User-Agent": f"magister-connector-agent/{agent_version}",
        },
    )


def check(
    config: AgentConfig,
    secrets: AgentSecrets,
    *,
    agent_version: str,
    transport: httpx.BaseTransport | None = None,
) -> UpdateInfo | None:
    """Was bereitliegt — oder ``None``, wenn die Plattform kein MSI anbietet."""
    with _client(config, secrets, agent_version=agent_version, transport=transport) as client:
        resp = client.get("/connector/update")
    if resp.status_code == 404:
        return None
    if resp.status_code == 401:
        raise UpdateError("Die Plattform hat den Agenten abgewiesen (401). Widerrufen?")
    if resp.status_code != 200:
        raise UpdateError(f"Die Plattform antwortete mit HTTP {resp.status_code}.")
    body: object = resp.json()
    if not isinstance(body, dict):
        raise UpdateError("Unlesbare Antwort der Plattform.")
    raw = cast(dict[str, Any], body)
    info = UpdateInfo(
        filename=str(raw.get("filename", "")),
        version=str(raw.get("version", "")),
        sha256=str(raw.get("sha256", "")).lower(),
        size_bytes=int(raw.get("size_bytes") or 0),
    )
    if not _DATEINAME.match(info.filename) or not re.fullmatch(r"[0-9a-f]{64}", info.sha256):
        raise UpdateError("Die Plattform nannte kein gültiges Agenten-MSI.")
    return info


def download(
    config: AgentConfig,
    secrets: AgentSecrets,
    info: UpdateInfo,
    *,
    agent_version: str,
    transport: httpx.BaseTransport | None = None,
) -> Path:
    """MSI ins Zustandsverzeichnis laden und gegen die SHA-256 prüfen."""
    ziel_dir = config.state_dir / "updates"
    ziel_dir.mkdir(parents=True, exist_ok=True)
    ziel = ziel_dir / info.filename
    # Frühere Updates (MSI, Skript, Protokoll) weg — je rund 30 MiB, und sie
    # werden nie wieder gebraucht.
    for alt in ziel_dir.iterdir():
        if alt.is_file() and not alt.name.startswith(ziel.stem):
            alt.unlink(missing_ok=True)
    teil = ziel.with_suffix(".teil")
    h = hashlib.sha256()
    groesse = 0
    with (
        _client(config, secrets, agent_version=agent_version, transport=transport) as client,
        client.stream("GET", "/connector/update/package") as resp,
    ):
        if resp.status_code != 200:
            raise UpdateError(f"Download scheiterte mit HTTP {resp.status_code}.")
        with teil.open("wb") as datei:
            for block in resp.iter_bytes():
                groesse += len(block)
                if groesse > MAX_BYTES:
                    raise UpdateError("Das Paket ist grösser als jedes Agenten-MSI.")
                h.update(block)
                datei.write(block)
    if h.hexdigest() != info.sha256:
        teil.unlink(missing_ok=True)
        raise UpdateError(
            "Die Prüfsumme des heruntergeladenen MSI stimmt nicht — nichts installiert."
        )
    teil.replace(ziel)
    return ziel


def install_script(msi: Path, log: Path) -> str:
    """Das Skript, das nach dem Ende dieses Prozesses installiert und startet."""
    return "\r\n".join(
        [
            "@echo off",
            "rem Von 'magister-connector update' geschrieben.",
            "rem Kurz warten, bis die Kommandozeile beendet ist.",
            "ping -n 6 127.0.0.1 >nul",
            f"sc stop {SERVICE} >nul 2>&1",
            f'msiexec /i "{msi}" /qn /norestart /l*v "{log}"',
            f"sc start {SERVICE} >nul 2>&1",
            "",
        ]
    )


def launch_install(msi: Path) -> Path:
    """Installation abgekoppelt starten. Rückgabe: Pfad des MSI-Protokolls."""
    if not IS_WINDOWS:
        raise UpdateError("Ein MSI lässt sich nur unter Windows einspielen.")
    log = msi.with_suffix(".log")
    script = msi.with_suffix(".cmd")
    script.write_text(install_script(msi, log), encoding="ascii")
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(  # noqa: S603 - festes Skript im abgedichteten Zustandsverzeichnis
        [str(system32 / "cmd.exe"), "/c", str(script)],
        creationflags=flags,
        close_fds=True,
        cwd=str(system32),
    )
    return log


__all__ = [
    "UpdateError",
    "UpdateInfo",
    "check",
    "download",
    "install_script",
    "is_newer",
    "launch_install",
    "parse_version",
]
