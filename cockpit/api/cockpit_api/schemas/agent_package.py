"""Ein Paket des Connector-Agenten, wie es die Konsole anbietet (ADR-0014)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AgentPackageOut(BaseModel):
    filename: str
    size_bytes: int
    #: Damit die Kunden-IT prüfen kann, dass die Datei heil angekommen ist.
    #: Keine Aussage über die Herkunft — dafür ist die Signatur zuständig.
    sha256: str
    modified_at: datetime


class PlatformCaOut(BaseModel):
    """Das Stammzertifikat der Plattform, für ``enroll --ca`` auf dem DC."""

    filename: str
    subject: str
    not_after: datetime
    #: SHA-256 über das DER-Zertifikat (nicht über die Datei). Auf dem DC in
    #: PowerShell: ``(Get-PfxCertificate root.pem).GetCertHashString('SHA256')``.
    sha256: str


class AgentUpdateOut(BaseModel):
    """Das neueste Agenten-MSI — Anzeige im Cockpit und Grundlage für ``update``."""

    filename: str
    version: str
    sha256: str
    size_bytes: int
