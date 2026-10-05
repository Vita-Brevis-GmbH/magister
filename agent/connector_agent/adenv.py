"""Die AD-Zugangsdaten des Dienstes — auch für ``check`` von Hand.

Der Dienst bekommt ``MAGISTER_AD_*`` aus seiner eigenen Umgebung: unter
Windows aus dem Registrierungswert ``Environment`` des Dienstes, unter Linux
aus der ``EnvironmentFile`` der systemd-Unit. Eine Eingabeaufforderung, in der
jemand ``magister-connector check`` tippt, hat davon nichts. Ohne diesen
Schritt prüfte ``check`` das AD mit leerer Konfiguration und meldete „AD-Zugang
unvollständig" auf einem Server, auf dem der Dienst einwandfrei läuft.

Gelesen wird nur, was mit ``MAGISTER_`` beginnt, und nur, was in der
aktuellen Umgebung noch fehlt — wer zum Ausprobieren einen Wert von Hand
setzt, überstimmt den Dienst. Werte werden nie ausgegeben, nur ihre Namen.
"""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

SERVICE_NAME = "MagisterConnector"
SERVICE_KEY = rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}"
#: Dieselbe Datei wie ``EnvironmentFile=`` in ``deploy/magister-connector.service``.
LINUX_ENV_FILE = Path("/etc/magister-connector/ad.env")
PREFIX = "MAGISTER_"


@dataclass(frozen=True, slots=True)
class ServiceEnvironment:
    #: Wo die Werte herkommen, für die Ausgabe von ``check``.
    source: str
    values: dict[str, str]


def parse_env_lines(lines: list[str]) -> dict[str, str]:
    """``KEY=VALUE`` je Zeile, wie systemd ``EnvironmentFile`` sie liest."""
    out: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key.startswith(PREFIX):
            out[key] = value
    return out


def _from_registry() -> ServiceEnvironment | None:
    # Über importlib: `winreg` gibt es nur unter Windows, und pyright prüft
    # diese Datei auch unter Linux. So bleibt der Rest der Datei strikt typisiert.
    winreg: Any = importlib.import_module("winreg")
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SERVICE_KEY) as key:
            value: object = winreg.QueryValueEx(key, "Environment")[0]
    except OSError:
        return None
    if isinstance(value, list):
        lines = [str(v) for v in cast(list[object], value)]
    else:
        lines = str(value).split("\0")
    return ServiceEnvironment(
        source=rf"Dienst-Umgebung (HKLM\{SERVICE_KEY}\Environment)",
        values=parse_env_lines(lines),
    )


def _from_file(path: Path) -> ServiceEnvironment | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return ServiceEnvironment(source=str(path), values=parse_env_lines(text.splitlines()))


def service_environment(env_file: Path = LINUX_ENV_FILE) -> ServiceEnvironment | None:
    """Die Umgebung, die der Dienst bekommt — oder ``None``, wenn keine da ist."""
    if sys.platform == "win32":
        return _from_registry()
    return _from_file(env_file)


def apply_missing(
    service: ServiceEnvironment, environ: MutableMapping[str, str] | None = None
) -> list[str]:
    """Fehlende Werte in die Umgebung übernehmen. Rückgabe: deren Namen."""
    target = os.environ if environ is None else environ
    applied: list[str] = []
    for key, value in service.values.items():
        if key not in target:
            target[key] = value
            applied.append(key)
    return sorted(applied)


__all__ = [
    "LINUX_ENV_FILE",
    "ServiceEnvironment",
    "apply_missing",
    "parse_env_lines",
    "service_environment",
]
