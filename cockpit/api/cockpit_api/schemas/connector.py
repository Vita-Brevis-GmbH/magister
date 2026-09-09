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


class AgentRenewRequest(BaseModel):
    """Zertifikatserneuerung (ADR-0014).

    Nur ein CSR — **kein Token**. Beglaubigt wird die Anfrage durch das
    bestehende Client-Zertifikat und den API-Key: wer den aktuellen Schlüssel
    besitzt, darf einen neuen bekommen. Ein Einmal-Token zu verlangen hiesse,
    dass alle 90 Tage ein Mensch beim Kunden vorbeimuss, und genau das ist der
    Zustand, den diese Erneuerung abschafft.

    Der CSR trägt ein **neues** Schlüsselpaar. Dasselbe wiederzuverwenden wäre
    einfacher (der Fingerprint bliebe gleich, es bräuchte kein
    Übergangsfenster) und falsch: ein Schlüssel, der über Jahre auf einem
    Kundenserver liegt, wird nie gewechselt. Die Erneuerung ist die
    Gelegenheit.
    """

    csr_pem: str = Field(min_length=64, max_length=8192)
    agent_version: str | None = Field(default=None, max_length=64)


class AgentRenewResponse(BaseModel):
    """Das neue Zertifikat.

    **Ohne** API-Key und HMAC-Schlüssel: die bleiben unverändert. Sie in
    derselben Antwort mitzudrehen wäre bequem und riskant — geht die Antwort
    auf dem Rückweg verloren, hätte der Agent einen alten API-Key zu einem
    neuen Zertifikat, und dann helfen auch zwei gültige Fingerprints nicht
    mehr. Ein Ding zur Zeit.
    """

    certificate_pem: str
    spki_sha256: str
    certificate_not_after: datetime
    #: Bis wann der alte Fingerprint zusätzlich gilt. Der Agent braucht das
    #: nicht, aber es steht in seinem Protokoll — und wenn jemand eine
    #: Aussperrung untersucht, ist es die erste Frage.
    previous_valid_until: datetime


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    status: AgentStatus
    spki_sha256: str
    certificate_serial: str
    certificate_not_after: datetime
    #: Läuft gerade eine Erneuerung, für die der Agent den neuen Fingerprint
    #: noch nicht bestätigt hat? Gesetzt heisst: er hat sich seit der
    #: Erneuerung noch nicht mit dem neuen Schlüssel gemeldet. Steht in der
    #: Auskunft, weil es die erste Frage ist, wenn ein Agent nach einer
    #: Erneuerung stumm wird.
    previous_spki_sha256: str | None = None
    spki_rotated_at: datetime | None = None
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
    #: ``Any``: die Methoden der Allowlist liefern String, Liste, Bool oder
    #: Paar — nicht nur Objekte. Siehe ConnectorJob.result.
    result: Any = None
    error: str | None = Field(default=None, max_length=2000)
    #: HMAC über Auftrags-Id und Ergebniskörper, hex.
    signature: str = Field(min_length=64, max_length=64)


class JobDetailOut(BaseModel):
    """Ein Auftrag samt Ergebnis — für die Datenebene, nicht für die Liste.

    Anders als ``JobOut`` trägt dieses Schema ``result``: die Datenebene
    braucht es, um dem Aufrufer zu antworten. ``payload`` fehlt weiter, denn
    der kann ein Passwort enthalten und wird nach Abschluss ohnehin gelöscht.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    method: str
    state: JobState
    result: Any
    error: str | None
    expires_at: datetime
    finished_at: datetime | None
