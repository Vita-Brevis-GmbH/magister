"""Bereitstellungs-Auftrag: wiederaufnehmbar, nie halb angelegt (ADR-0013 D2).

Ein Kunde anzulegen sind fünf Schritte an zwei verschiedenen Systemen
(Konsolen-DB und Magister-Cluster). Ohne Protokoll wäre ein Abbruch in der
Mitte ein Zustand, den niemand mehr auseinandersortiert: existiert die Rolle
schon? ist das Schema migriert? Deshalb hält der Auftrag jeden Schritt
einzeln, und jeder Schritt ist für sich wiederholbar.

Die Regel dahinter: **ein abgebrochener Auftrag lässt den Kunden auf
``provisioning`` und damit unerreichbar.** Lieber gar nicht bedient als halb.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cockpit_api.models.base import Base, enum_column


class JobStatus(enum.StrEnum):
    pending = "pending"
    running = "running"
    failed = "failed"
    succeeded = "succeeded"


class ProvisioningStep(enum.StrEnum):
    """Die Schritte in ihrer Reihenfolge.

    Reihenfolge ist nicht beliebig: die Rolle muss vor dem Schema existieren
    (das Schema gehört ihr), das Schema vor der Migration, und aktiv wird der
    Kunde erst, wenn alles davor steht.
    """

    create_role = "create_role"
    create_schema = "create_schema"
    migrate = "migrate"
    data_key = "data_key"
    activate = "activate"


#: Reihenfolge als Liste — ``StrEnum`` garantiert sie nicht, und hier hängt
#: Korrektheit daran.
STEP_ORDER: tuple[ProvisioningStep, ...] = (
    ProvisioningStep.create_role,
    ProvisioningStep.create_schema,
    ProvisioningStep.migrate,
    ProvisioningStep.data_key,
    ProvisioningStep.activate,
)


class ProvisioningJob(Base):
    __tablename__ = "provisioning_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus, name="provisioning_job_status"), default=JobStatus.pending
    )
    #: Bis hierher ist es gelaufen. ``None`` heisst: noch kein Schritt fertig.
    last_completed_step: Mapped[ProvisioningStep | None] = mapped_column(
        enum_column(ProvisioningStep, name="provisioning_step"), default=None
    )
    #: Protokoll je Schritt: ``[{"step": ..., "ok": bool, "detail": str, "at": iso}]``.
    #: Bewusst JSONB und keine eigene Tabelle: es wird nur angehängt und im
    #: Ganzen gelesen, und der Auftrag bleibt in einer Zeile begreifbar.
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    #: Fehlertext des letzten gescheiterten Schritts. Nie ein Passwort — die
    #: Dienste geben Klartextgeheimnisse nur an den Aufrufer zurück.
    last_error: Mapped[str | None] = mapped_column(String(2000), default=None)
    attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
