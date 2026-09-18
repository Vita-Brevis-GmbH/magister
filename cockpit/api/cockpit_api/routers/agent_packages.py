"""Die Pakete des Connector-Agenten zum Herunterladen (ADR-0014).

Warum aus der Konsole und nicht aus einem Release-Archiv: beim Onboarding
sitzt man mit der Kunden-IT zusammen, hat den Einmal-Token gerade erzeugt
und braucht die Datei jetzt. Sie aus derselben Oberfläche zu holen, in der
der Token entsteht, spart den Umweg — und die Prüfsumme kommt aus derselben
Quelle wie die Datei, statt aus einer Mail daneben.

Drei Dinge, die diese Fläche NICHT tut:

* **Sie ist nicht öffentlich.** Nur eine angemeldete Person kommt daran
  (ADR-0020 D4). Ein Agentenpaket ist kein Geheimnis, aber es ist auch
  nichts, was ohne Grund im Netz stehen muss.
* **Sie baut nichts.** Die Pakete entstehen in der CI und werden in das
  Verzeichnis gelegt; die Konsole liest nur.
* **Sie ersetzt die Signatur nicht.** Die Prüfsumme sagt „diese Datei ist
  die, die hier liegt" — nicht „sie kommt von Vita Brevis". Dafür ist die
  Paketsignatur zuständig (Entscheid E18).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from cockpit_api.auth import Caller, require_person
from cockpit_api.config import settings
from cockpit_api.schemas.agent_package import AgentPackageOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent-packages", tags=["agent-packages"])

#: Was ausgeliefert wird. Alles andere im Verzeichnis (Signaturen,
#: Prüfsummendateien, halbe Uploads) bleibt liegen.
ERLAUBTE_ENDUNGEN = (".msi", ".deb", ".exe", ".zip")


def _verzeichnis() -> Path:
    if not settings.agent_package_dir:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "COCKPIT_AGENT_PACKAGE_DIR ist nicht gesetzt — kein Verzeichnis mit Agentenpaketen.",
        )
    pfad = Path(settings.agent_package_dir)
    if not pfad.is_dir():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"{settings.agent_package_dir} ist kein Verzeichnis.",
        )
    return pfad


def _pruefsumme(datei: Path) -> str:
    h = hashlib.sha256()
    with datei.open("rb") as strom:
        for block in iter(lambda: strom.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


@router.get("", response_model=list[AgentPackageOut])
async def list_packages(_: Caller = Depends(require_person)) -> list[AgentPackageOut]:
    """Was zum Herunterladen bereitliegt, mit Grösse und Prüfsumme."""
    pfad = _verzeichnis()
    pakete: list[AgentPackageOut] = []
    for datei in sorted(pfad.iterdir()):
        if not datei.is_file() or datei.suffix.lower() not in ERLAUBTE_ENDUNGEN:
            continue
        stat = datei.stat()
        pakete.append(
            AgentPackageOut(
                filename=datei.name,
                size_bytes=stat.st_size,
                sha256=_pruefsumme(datei),
                modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
            )
        )
    return pakete


@router.get("/{filename}")
async def download_package(filename: str, caller: Caller = Depends(require_person)) -> FileResponse:
    """Eine Datei ausliefern — und nur eine aus diesem Verzeichnis.

    `Path(filename).name` streicht jeden Pfadanteil: `../../etc/shadow` wird
    zu `shadow`, und das liegt dort nicht. Zusätzlich wird der aufgelöste
    Pfad gegen das Verzeichnis geprüft, damit auch ein Symlink nicht
    hinausführt.
    """
    pfad = _verzeichnis()
    ziel = (pfad / Path(filename).name).resolve()
    if pfad.resolve() not in ziel.parents or not ziel.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kein solches Paket.")
    if ziel.suffix.lower() not in ERLAUBTE_ENDUNGEN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kein solches Paket.")
    # Wer welches Paket geholt hat, gehört ins Log des Betreibers: beim
    # Onboarding ist das die Antwort auf „welche Fassung haben wir dem
    # Kunden gegeben?".
    logger.info("Agentenpaket %s an %s ausgeliefert.", ziel.name, caller.actor)
    return FileResponse(ziel, filename=ziel.name, media_type="application/octet-stream")


__all__ = ["router"]
