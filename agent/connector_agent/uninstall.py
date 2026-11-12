"""Den Agenten sauber entfernen (``magister-connector uninstall``).

Vorher hiess Deinstallieren: über „Apps & Features" das Programm entfernen —
und zwei Dinge blieben stehen, beide mit Absicht, beide unbequem:

* die **Anmeldung in der Konsole**. Sie galt weiter, bis jemand dort von Hand
  widerrief; eine Anmeldung, zu der es keinen Agenten mehr gibt.
* das **Zustandsverzeichnis** mit privatem Schlüssel und API-Key. Eine Kopie
  davon ist ein vollwertiger Zugang zum AD des Kunden über die Plattform.

Dieser Befehl macht die Schritte in der Reihenfolge, in der sie sicher sind:

1. Dienst anhalten — sonst holt er während des Abbaus noch Aufträge.
2. Bei der Plattform **abmelden** (widerrufen), solange Schlüssel und API-Key
   noch da sind. Danach geht das nicht mehr: ohne Schlüssel kann der Agent
   nicht mehr beweisen, wer er ist.
3. Schlüssel, Zertifikat und Geheimnisse löschen.
4. Das Programm selbst entfernen (``msiexec /x``). Ausgeliefert wird der
   Agent nur noch als MSI für den Domänencontroller.

Scheitert die Abmeldung (Plattform nicht erreichbar), wird trotzdem gelöscht
— der Schlüssel ist danach weg, und mit ihm jede Möglichkeit, die Anmeldung
zu benutzen. Der Befehl sagt dann ausdrücklich, dass in der Konsole noch zu
widerrufen ist, damit die Liste dort stimmt.
"""

from __future__ import annotations

import importlib
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from connector_agent.config import IS_WINDOWS, AgentConfig, AgentSecrets
from connector_agent.diagnose import explain_transport_error
from connector_agent.renewal import PREV_SUFFIX
from connector_agent.tls import TlsSetupError, build_context

logger = logging.getLogger(__name__)

#: Name des Windows-Dienstes.
WINDOWS_SERVICE = "MagisterConnector"

#: So steht das Paket unter „Apps & Features" (Product/@Name in der .wxs).
MSI_DISPLAY_NAME = "Magister Connector-Agent"


class DeregisterError(RuntimeError):
    """Die Abmeldung bei der Plattform ist gescheitert."""


@dataclass
class UninstallReport:
    """Was geschehen ist — für die Ausgabe und für die Tests."""

    service: str = ""
    deregistered: bool = False
    deregister_problem: str = ""
    removed: list[Path] = field(default_factory=list[Path])
    package: str = ""


def deregister(
    config: AgentConfig,
    secrets: AgentSecrets,
    *,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Bei der Plattform abmelden. Danach ist dieser Agent dort widerrufen.

    Ein 401 heisst: die Plattform kennt den Agenten nicht mehr als gültig —
    schon widerrufen oder der Kunde gesperrt. Für eine Deinstallation ist das
    kein Fehler; das Ziel ist erreicht.
    """
    try:
        context = build_context(
            ca_bundle=config.ca_bundle, cert=config.cert_path, key=config.key_path
        )
    except TlsSetupError as exc:
        raise DeregisterError(str(exc)) from exc
    try:
        with httpx.Client(
            timeout=30.0,
            verify=context,
            trust_env=False,
            proxy=config.proxy,
            transport=transport,
            headers={"X-Connector-Api-Key": secrets.api_key},
        ) as client:
            resp = client.post(f"{config.endpoint}/connector/decommission")
    except httpx.HTTPError as exc:
        raise DeregisterError(explain_transport_error(exc, config)) from exc
    if resp.status_code in (204, 401):
        return
    raise DeregisterError(f"Die Plattform antwortete mit HTTP {resp.status_code}.")


def is_admin() -> bool:
    """Läuft der Befehl mit Administratorrechten?"""
    # `sys.platform` und nicht IS_WINDOWS: nur so erkennt pyright auf beiden
    # Systemen, dass `os.geteuid` unter Windows nie erreicht wird.
    if sys.platform == "win32":
        import ctypes

        windll: Any = getattr(ctypes, "windll")  # noqa: B009 - nur unter Windows vorhanden
        return bool(windll.shell32.IsUserAnAdmin())
    return os.geteuid() == 0


def _system32() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


def stop_service() -> str:
    """Dienst anhalten. Gibt zurück, was geschah — scheitert nie laut."""
    if not IS_WINDOWS:
        return "kein Windows-Dienst hier — nichts angehalten"
    cmd = [str(_system32() / "sc.exe"), "stop", WINDOWS_SERVICE]
    try:
        done = subprocess.run(  # noqa: S603 - fester Befehl mit absolutem Pfad
            cmd, capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"nicht angehalten ({type(exc).__name__})"
    # `sc stop` meldet 1062, wenn der Dienst schon steht — für uns dasselbe.
    if done.returncode == 0 or "1062" in done.stdout:
        return "angehalten"
    return f"nicht angehalten (Code {done.returncode}) — läuft er überhaupt?"


def start_service() -> str:
    """Dienst starten (nach ``enroll``). Gibt zurück, was geschah — scheitert nie laut."""
    if not IS_WINDOWS:
        return "nur unter Windows — hier von Hand starten"
    cmd = [str(_system32() / "sc.exe"), "start", WINDOWS_SERVICE]
    try:
        done = subprocess.run(  # noqa: S603 - fester Befehl mit absolutem Pfad
            cmd, capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"nicht gestartet ({type(exc).__name__})"
    # `sc start` meldet 1056, wenn er schon läuft — für uns dasselbe.
    if done.returncode == 0 or "1056" in done.stdout:
        return "gestartet"
    return f"nicht gestartet (Code {done.returncode}) — Ereignisprotokoll ansehen"


def credential_files(config: AgentConfig) -> list[Path]:
    """Die Dateien, die einen Zugang darstellen: Schlüssel, Zertifikat, Geheimnisse."""
    files: list[Path] = []
    for path in (config.key_path, config.cert_path):
        files += [path, path.with_name(path.name + PREV_SUFFIX)]
    files.append(config.secrets_path)
    return files


def wipe(config: AgentConfig, *, everything: bool, config_path: Path) -> list[Path]:
    """Zugangsdateien löschen; mit ``everything`` das ganze Zustandsverzeichnis.

    Ohne ``everything`` bleiben ``config.json`` und das Protokoll stehen: die
    Konfiguration für eine Neuinstallation auf demselben Server, das Protokoll
    für die Frage, warum deinstalliert wurde.
    """
    removed: list[Path] = []
    for path in credential_files(config):
        if path.exists():
            path.unlink()
            removed.append(path)
    if everything:
        if config_path.exists() and config_path.parent != config.state_dir:
            config_path.unlink()
            removed.append(config_path)
        if config.state_dir.exists():
            shutil.rmtree(config.state_dir)
            removed.append(config.state_dir)
    return removed


def windows_product_code() -> str | None:
    """Produktcode des installierten MSI, aus der Liste der Programme.

    Der Code ändert sich mit jedem Build (``Product Id="*"``); fest ist nur der
    Name. Gesucht wird in der 64-Bit-Ansicht, in die das Paket sich einträgt.
    """
    if not IS_WINDOWS:
        return None
    # Über importlib: `winreg` gibt es nur unter Windows.
    winreg: Any = importlib.import_module("winreg")
    root = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    flags = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root, 0, flags) as uninstall:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(uninstall, index)
            except OSError:
                return None
            index += 1
            try:
                with winreg.OpenKey(uninstall, name, 0, flags) as entry:
                    shown = winreg.QueryValueEx(entry, "DisplayName")[0]
            except OSError:
                continue
            if shown == MSI_DISPLAY_NAME and name.startswith("{"):
                return str(name)


def remove_package(*, keep: bool) -> str:
    """Das MSI entfernen."""
    if keep:
        return "behalten (--paket-behalten)"
    if not IS_WINDOWS:
        return "kein MSI hier — der Agent wird nur unter Windows als Paket ausgeliefert"
    code = windows_product_code()
    if code is None:
        return f"nicht gefunden — über „Apps & Features“ „{MSI_DISPLAY_NAME}“ entfernen"
    # Abgekoppelt starten: dieser Prozess läuft aus dem Installationsordner,
    # den msiexec gleich löscht. Er muss beendet sein, bevor msiexec dort
    # ankommt — sonst bleibt die Datei bis zum nächsten Neustart liegen.
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(  # noqa: S603 - fester Befehl, Code aus der Registry
        [str(_system32() / "msiexec.exe"), "/x", code, "/passive"],
        creationflags=flags,
        close_fds=True,
        cwd=os.environ.get("SystemRoot", r"C:\Windows"),
    )
    return f"msiexec /x {code} gestartet — das Fenster des Installationsprogramms folgt"


__all__ = [
    "DeregisterError",
    "UninstallReport",
    "credential_files",
    "deregister",
    "is_admin",
    "remove_package",
    "start_service",
    "stop_service",
    "windows_product_code",
    "wipe",
]
