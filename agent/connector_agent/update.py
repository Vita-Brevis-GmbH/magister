"""``magister-connector update`` — die neueste Fassung von der Plattform holen und einspielen.

Ein Befehl statt Herunterladen, Kopieren, Installieren, Dienst starten:

1. Die Plattform fragen, welche Fassung bereitliegt (``GET /connector/update``),
   über den beglaubigten Kanal — Client-Zertifikat und API-Key, wie jeder
   Auftrag. Dieselbe Datei, die das Cockpit unter „Agent herunterladen“ zeigt.
2. Nur wenn sie neuer ist als die laufende: das MSI ins Zustandsverzeichnis
   laden (nur SYSTEM und Administratoren) und die SHA-256 prüfen.
3. Ein abgekoppeltes Skript startet ``msiexec`` still und danach den Dienst.
   Abgekoppelt, weil dieses Programm aus dem Ordner läuft, den das MSI ersetzt.

Seit 2026-10 gibt es daneben das Selbstupdate im Wartungsfenster
(:mod:`connector_agent.autoupdate`). Beide Wege prüfen die **Ed25519-Signatur**
gegen die im Agenten eingebauten Schlüssel (:mod:`connector_agent.update_keys`):
die Plattform reicht MSI und Signatur nur durch und kann keines fälschen. Von
Hand lässt sich ein unsigniertes Paket mit ``--ohne-signatur`` erzwingen —
das entscheidet dann ein Administrator auf dem DC, nicht die Plattform.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, cast

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

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
    #: Ed25519-Signatur (Base64) über :func:`signed_message`, und mit welchem
    #: Schlüssel. Fehlt beides, liegt neben dem MSI keine ``.sig``.
    key_id: str | None = None
    signature: str | None = None


def signed_message(filename: str, version: str, sha256: str) -> bytes:
    """Was signiert wird: Name, Fassung und Prüfsumme — nicht die ganze Datei.

    Die Prüfsumme bindet die Datei (der Agent prüft sie nach dem Laden), die
    Fassung verhindert, dass ein altes, signiertes Paket als neues ausgegeben
    wird. Der Vorsatz trennt diese Signatur von jeder anderen mit demselben
    Schlüssel.
    """
    return f"magister-connector-update/v1\n{filename}\n{version}\n{sha256.lower()}\n".encode()


def verify_signature(info: UpdateInfo, keys: dict[str, str]) -> None:
    """Wirft :class:`UpdateError`, wenn die Signatur fehlt oder nicht passt."""
    if not info.signature or not info.key_id:
        raise UpdateError(f"{info.filename} ist nicht signiert.")
    public = keys.get(info.key_id)
    if public is None:
        raise UpdateError(
            f"{info.filename} ist mit einem unbekannten Schlüssel signiert ({info.key_id})."
        )
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public))
        key.verify(
            base64.b64decode(info.signature),
            signed_message(info.filename, info.version, info.sha256),
        )
    except (InvalidSignature, ValueError, binascii.Error) as exc:
        raise UpdateError(f"Die Signatur von {info.filename} stimmt nicht.") from exc


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
        key_id=str(raw["key_id"]) if raw.get("key_id") else None,
        signature=str(raw["signature"]) if raw.get("signature") else None,
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
    ziel_dir = updates_dir(config)
    ziel_dir.mkdir(parents=True, exist_ok=True)
    ziel = ziel_dir / info.filename
    # Frühere Updates (MSI, Skript, Protokoll) weg — je rund 30 MiB. Bleiben
    # darf das MSI der laufenden Fassung: es ist der Rückfall, wenn die neue
    # nicht startet. Merkzettel des Selbstupdates (.txt) bleiben ebenfalls.
    behalten = msi_prefix(agent_version)
    for alt in ziel_dir.iterdir():
        if not alt.is_file() or alt.suffix.lower() not in {".msi", ".cmd", ".log", ".teil"}:
            continue
        if alt.name.startswith(ziel.stem) or (behalten and alt.name.startswith(behalten)):
            continue
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


def updates_dir(config: AgentConfig) -> Path:
    return config.state_dir / "updates"


def msi_prefix(version: str) -> str | None:
    """``0.2.190 (abc)`` → ``magister-connector-0.2.190-x64``; ohne Fassung ``None``."""
    parsed = parse_version(version)
    if parsed is None:
        return None
    return "magister-connector-{}.{}.{}-x64".format(*parsed)


def msi_for_version(config: AgentConfig, version: str) -> Path | None:
    """Das geladene MSI einer Fassung, wenn es noch daliegt — der Rückfall."""
    prefix = msi_prefix(version)
    folder = updates_dir(config)
    if prefix is None or not folder.is_dir():
        return None
    for datei in sorted(folder.iterdir()):
        if datei.suffix.lower() == ".msi" and datei.name.startswith(prefix):
            return datei
    return None


#: Standard-Installationsordner (wie INSTALLDIR in der .wxs).
DEFAULT_INSTALL_DIR = Path(r"C:\Program Files\Magister Connector")


def install_dir() -> Path:
    """Der Ordner, aus dem dieses Programm läuft — als Paket, sonst der Standard."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return DEFAULT_INSTALL_DIR


#: Ergebnis des letzten Einspielens, neben dem Protokoll. Der neu gestartete
#: Agent meldet es der Plattform (Cockpit → Connector).
RESULT_FILE = "update-ergebnis.txt"


def _wait_for_stop() -> list[str]:
    """Zeilen: warten, bis der Dienst steht (bis 60 s), sonst den Prozess beenden."""
    return [
        f"sc stop {SERVICE} >nul 2>&1",
        "set /a n=0",
        ":warten%1",
        f"sc query {SERVICE} >nul 2>&1 || goto steht%1",
        f'sc query {SERVICE} | findstr /c:"STOPPED" >nul && goto steht%1',
        "set /a n+=1",
        "if %n% geq 30 goto erzwingen%1",
        "ping -n 3 127.0.0.1 >nul",
        "goto warten%1",
        ":erzwingen%1",
        "taskkill /f /im magister-connector-service.exe >nul 2>&1",
        "ping -n 3 127.0.0.1 >nul",
        ":steht%1",
    ]


def install_script(
    msi: Path,
    log: Path,
    *,
    target: Path = DEFAULT_INSTALL_DIR,
    previous: Path | None = None,
) -> str:
    """Das Skript, das nach dem Ende dieses Prozesses installiert und startet.

    Was ein nacktes ``msiexec`` nach ``sc stop`` nicht leistet — beim ersten
    Kunden fehlte danach ``_internal\\python312.dll``, und kein Befehl des
    Agenten startete mehr:

    * **Warten, bis der Dienst wirklich steht.** ``sc stop`` kehrt sofort
      zurück. Läuft der Dienst noch, sind seine Dateien in Gebrauch, und das
      MSI verschiebt sie auf den nächsten Neustart. Nach 60 Sekunden wird der
      Prozess beendet.
    * **Jede Datei neu schreiben** (``REINSTALLMODE=amus``). Sonst lässt das
      MSI eine Datei gleicher Version liegen, die das Entfernen der alten
      Fassung danach löscht — die Python-DLL ändert sich zwischen zwei
      Agent-Fassungen nie.
    * **Nachsehen und reparieren.** Fehlt die Python-DLL trotzdem, einmal
      ``msiexec /fa`` (alle Dateien neu).
    * **Gesundheitsprüfung und Rückfall.** 90 Sekunden nach dem Start muss
      der Dienst laufen und ``magister-connector --version`` antworten.
      Sonst, wenn ``previous`` (das MSI der bisherigen Fassung) daliegt: neue
      Fassung entfernen, alte wieder einspielen.

    Das Ergebnis steht in :data:`RESULT_FILE` neben dem Protokoll.
    """
    result = log.with_name(RESULT_FILE)
    folder = PureWindowsPath(target)
    dll = folder / "_internal" / "python3*.dll"
    exe = folder / "magister-connector.exe"
    lines = [
        "@echo off",
        "rem Von 'magister-connector update' geschrieben.",
        "rem Kurz warten, bis der aufrufende Prozess beendet ist.",
        "ping -n 6 127.0.0.1 >nul",
        *[line.replace("%1", "") for line in _wait_for_stop()],
        f'msiexec /i "{msi}" /qn /norestart REINSTALLMODE=amus /l*v "{log}"',
        "set rc=%errorlevel%",
        f'if exist "{dll}" goto fertig',
        f'msiexec /fa "{msi}" /qn /norestart /l*v+ "{log}"',
        "set rc=%rc% repariert:%errorlevel%",
        ":fertig",
        f"sc start {SERVICE} >nul 2>&1",
        "rem Gesundheitsprüfung: läuft der Dienst, antwortet der Agent?",
        "ping -n 91 127.0.0.1 >nul",
        f'sc query {SERVICE} | findstr /c:"RUNNING" >nul || goto krank',
        f'"{exe}" --version >nul 2>&1 || goto krank',
        "set rc=%rc% gesund",
        "goto ende",
        ":krank",
        "set rc=%rc% gesund:nein",
    ]
    if previous is not None:
        lines += [
            f'if not exist "{previous}" goto ende',
            *[line.replace("%1", "2") for line in _wait_for_stop()],
            f'msiexec /x "{msi}" /qn /norestart /l*v+ "{log}"',
            f'msiexec /i "{previous}" /qn /norestart REINSTALLMODE=amus /l*v+ "{log}"',
            "set rc=%rc% rueckfall:%errorlevel%",
            f"sc start {SERVICE} >nul 2>&1",
        ]
    lines += [
        ":ende",
        f'echo {msi.name} msiexec:%rc% > "{result}"',
        "",
    ]
    return "\r\n".join(lines)


def launch_install(msi: Path, previous: Path | None = None) -> Path:
    """Installation abgekoppelt starten. Rückgabe: Pfad des MSI-Protokolls."""
    if not IS_WINDOWS:
        raise UpdateError("Ein MSI lässt sich nur unter Windows einspielen.")
    log = msi.with_suffix(".log")
    script = msi.with_suffix(".cmd")
    script.write_text(
        install_script(msi, log, target=install_dir(), previous=previous), encoding="ascii"
    )
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(  # noqa: S603 - festes Skript im abgedichteten Zustandsverzeichnis
        [str(system32 / "cmd.exe"), "/c", str(script)],
        creationflags=flags,
        close_fds=True,
        cwd=str(system32),
    )
    return log


def report(
    config: AgentConfig,
    secrets: AgentSecrets,
    outcome: str,
    *,
    agent_version: str,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Ergebnis eines Updates an die Plattform melden (Anzeige im Cockpit)."""
    with _client(config, secrets, agent_version=agent_version, transport=transport) as client:
        resp = client.post("/connector/update/result", json={"outcome": outcome[:500]})
    if resp.status_code not in (200, 204):
        raise UpdateError(f"Meldung abgewiesen: HTTP {resp.status_code}.")


__all__ = [
    "RESULT_FILE",
    "UpdateError",
    "UpdateInfo",
    "check",
    "download",
    "install_dir",
    "install_script",
    "is_newer",
    "launch_install",
    "msi_for_version",
    "msi_prefix",
    "parse_version",
    "report",
    "signed_message",
    "updates_dir",
    "verify_signature",
]
