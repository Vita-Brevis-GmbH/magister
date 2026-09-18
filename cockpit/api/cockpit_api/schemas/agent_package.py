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
