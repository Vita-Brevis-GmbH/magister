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

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from cockpit_api.auth import Caller, require_person
from cockpit_api.config import settings
from cockpit_api.schemas.agent_package import AgentPackageOut, AgentUpdateOut, PlatformCaOut
from cockpit_api.services.agent_update import newest_msi

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent-packages", tags=["agent-packages"])

#: Was ausgeliefert wird. Alles andere im Verzeichnis (Signaturen,
#: Prüfsummendateien, halbe Uploads) bleibt liegen. Kein ``.deb`` mehr: der
#: Agent läuft auf dem Domänencontroller (ADR-0014 Nachtrag); ein altes Paket
#: im Verzeichnis soll niemand mehr herunterladen.
ERLAUBTE_ENDUNGEN = (".msi", ".exe", ".zip")


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


#: Unter diesem Namen landet das Stammzertifikat beim Herunterladen — derselbe,
#: den INSTALL.txt und die Befehlszeile im Cockpit nennen.
PLATFORM_CA_FILENAME = "root.pem"


def _platform_ca() -> tuple[Path, x509.Certificate]:
    if not settings.platform_root_ca:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Kein eigenes Stammzertifikat eingerichtet (COCKPIT_PLATFORM_ROOT_CA) — "
            "die Plattform braucht dann keines auf dem DC.",
        )
    pfad = Path(settings.platform_root_ca)
    try:
        cert = x509.load_pem_x509_certificate(pfad.read_bytes())
    except FileNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"{pfad} gibt es im Container nicht."
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"{pfad} ist kein PEM-Zertifikat."
        ) from exc
    return pfad, cert


def newest_update() -> AgentUpdateOut | None:
    """Das neueste MSI mit Fassung im Namen, oder ``None``. Für Cockpit und Agent."""
    msi = newest_msi(_verzeichnis())
    if msi is None:
        return None
    return AgentUpdateOut(
        filename=msi.path.name,
        version=msi.version_text,
        sha256=msi.sha256(),
        size_bytes=msi.path.stat().st_size,
    )


# Vor `/{filename}`: sonst finge jene Route diesen Pfad ab.
@router.get("/latest", response_model=AgentUpdateOut)
async def latest_package(_: Caller = Depends(require_person)) -> AgentUpdateOut:
    """Die neueste Agenten-Fassung — das Cockpit zeigt daran „Update verfügbar“."""
    latest = newest_update()
    if latest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kein MSI mit Fassung im Namen.")
    return latest


@router.get("/platform-ca/info", response_model=PlatformCaOut)
async def platform_ca_info(_: Caller = Depends(require_person)) -> PlatformCaOut:
    """Wem das Stammzertifikat gehört und sein Fingerprint — zum Vergleich auf dem DC."""
    _pfad, cert = _platform_ca()
    return PlatformCaOut(
        filename=PLATFORM_CA_FILENAME,
        subject=cert.subject.rfc4514_string(),
        not_after=cert.not_valid_after_utc,
        sha256=cert.fingerprint(hashes.SHA256()).hex(),
    )


@router.get("/platform-ca")
async def download_platform_ca(caller: Caller = Depends(require_person)) -> FileResponse:
    """Das Stammzertifikat der Plattform, für `magister-connector enroll --ca`.

    Nur das öffentliche Zertifikat; der Schlüssel liegt nie im Container der
    Konsole.
    """
    pfad, _cert = _platform_ca()
    logger.info("Stammzertifikat der Plattform an %s ausgeliefert.", caller.actor)
    return FileResponse(pfad, filename=PLATFORM_CA_FILENAME, media_type="application/x-pem-file")


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
