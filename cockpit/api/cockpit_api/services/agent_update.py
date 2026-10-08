"""Welches Agenten-MSI das neueste ist — für das Cockpit und für `magister-connector update`.

Die Fassung steht im Dateinamen (``magister-connector-0.2.190-x64[-<commit>].msi``,
siehe ``agent/packaging/bau_fassung.py``). Pakete ohne Fassung im Namen
(``magister-connector-x64-<commit>.msi``) stammen aus der Zeit, als jedes MSI
„0.2.0“ hiess; sie werden nie als Update angeboten — sonst hielte ein Agent
ein älteres Paket für ein neueres.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_FASSUNG = re.compile(r"^magister-connector-(\d+)\.(\d+)\.(\d+)-x64(?:-[0-9a-f]{6,40})?\.msi$")


@dataclass(frozen=True, slots=True)
class AgentMsi:
    path: Path
    version: tuple[int, int, int]

    @property
    def version_text(self) -> str:
        return ".".join(str(part) for part in self.version)

    def sha256(self) -> str:
        h = hashlib.sha256()
        with self.path.open("rb") as strom:
            for block in iter(lambda: strom.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()


def version_of(filename: str) -> tuple[int, int, int] | None:
    match = _FASSUNG.match(filename)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def parse_version(text: str) -> tuple[int, int, int] | None:
    """``0.2.190`` oder ``0.2.190 (abc1234)`` → (0, 2, 190)."""
    match = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)", text or "")
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def newest_msi(directory: Path) -> AgentMsi | None:
    """Das MSI mit der höchsten Fassung; bei Gleichstand das jüngste."""
    best: AgentMsi | None = None
    best_mtime = 0.0
    for datei in directory.iterdir():
        if not datei.is_file():
            continue
        version = version_of(datei.name)
        if version is None:
            continue
        mtime = datei.stat().st_mtime
        if best is None or (version, mtime) > (best.version, best_mtime):
            best, best_mtime = AgentMsi(datei, version), mtime
    return best


__all__ = ["AgentMsi", "newest_msi", "parse_version", "version_of"]
