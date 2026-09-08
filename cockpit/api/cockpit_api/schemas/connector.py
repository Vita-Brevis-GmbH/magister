from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cockpit_api.models.connector import AgentStatus, JobState


class EnrollmentCreate(BaseModel):
    agent_name: str = Field(min_length=1, max_length=200)


class EnrollmentOut(BaseModel):
    """Das Ergebnis einer Token-Ausstellung.

    ``token`` kommt **genau einmal**. Es reist im Download-Paket zur Kunden-IT
    und ist 24 Stunden gültig; danach ist es wertlos.
    """

    id: UUID
    agent_name: str
    expires_at: datetime
    token: str


class AgentEnrollRequest(BaseModel):
    """Was der Agent bei der Anmeldung schickt.

    Kein Schlüssel: nur der CSR. Der private Schlüssel entsteht auf dem Agenten
    und verlässt ihn nie.
    """

    token: str = Field(min_length=16, max_length=200)
    csr_pem: str = Field(min_length=64, max_length=8192)
    agent_version: str | None = Field(default=None, max_length=64)


class AgentEnrollResponse(BaseModel):
    """Die Antwort auf eine geglückte Anmeldung.

    ``api_key`` und ``result_hmac_key`` kommen **genau einmal**. Die Konsole
    speichert den API-Key nur als argon2id-Hash; wer ihn verliert, dreht ihn.
    """

    agent_id: UUID
    certificate_pem: str
    spki_sha256: str
    certificate_not_after: datetime
    api_key: str
    result_hmac_key: str


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    status: AgentStatus
    spki_sha256: str
    certificate_serial: str
    certificate_not_after: datetime
    agent_version: str | None
    last_seen_at: datetime | None
    revoked_at: datetime | None
    revoked_reason: str | None
    created_at: datetime


class AgentRevoke(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class JobEnqueue(BaseModel):
    method: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] | None = None


class JobOut(BaseModel):
    """Ein Auftrag, wie die Konsole ihn zeigt.

    Ohne ``payload``: der kann ein Passwort tragen. Wer den Auftrag ansieht,
    soll wissen, *was* passiert ist, nicht *womit*.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    agent_id: UUID | None
    method: str
    state: JobState
    error: str | None
    payload_purged_at: datetime | None
    expires_at: datetime
    claimed_at: datetime | None
    finished_at: datetime | None
    attempts: int
    created_at: datetime


class JobForAgent(BaseModel):
    """Ein übernommener Auftrag, wie der Agent ihn bekommt — mit Nutzlast."""

    id: UUID
    method: str
    payload: dict[str, Any] | None
    expires_at: datetime


class JobResultIn(BaseModel):
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = Field(default=None, max_length=2000)
    #: HMAC über Auftrags-Id und Ergebniskörper, hex.
    signature: str = Field(min_length=64, max_length=64)
