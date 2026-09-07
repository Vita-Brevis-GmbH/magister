"""Schemas for the NinjaOne device connector (detail-view only, never stored)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NinjaDeviceSummary(BaseModel):
    """A live, transient view of the matched NinjaOne device — not persisted.

    Fields are best-effort: NinjaOne payload keys vary by API version, so an
    absent value is simply ``None`` (the UI shows a dash) rather than an error.
    """

    ninja_device_id: int
    system_name: str | None = None
    dns_name: str | None = None
    offline: bool | None = None
    last_contact: float | None = None
    os_name: str | None = None
    serial_number: str | None = None
    node_class: str | None = None
    organization_id: int | None = None


class NinjaScriptOut(BaseModel):
    """One entry of the NinjaOne automation/script library, for the picker."""

    id: int
    name: str


class NinjaStatusOut(BaseModel):
    """The single response the device detail view reads. Everything is live.

    - ``enabled`` False → the connector is not configured; show nothing.
    - ``matched`` False with ``ambiguous`` True → several NinjaOne devices share
      the hostname/serial; no automatic link, the operator resolves it in Ninja.
    - ``error`` set → NinjaOne was unreachable/failed; the rest is empty.
    """

    enabled: bool
    matched: bool = False
    ambiguous: bool = False
    via: str | None = None
    status: NinjaDeviceSummary | None = None
    scripts: list[NinjaScriptOut] = Field(default_factory=list)
    error: str | None = None


class NinjaRunScriptRequest(BaseModel):
    """Run one library script on the NinjaOne device this Magister device maps to.

    No NinjaOne device id is accepted from the client — the server re-matches
    from the Magister device, so a script can only ever target the mapped device.
    """

    script_id: int
    parameters: str | None = Field(default=None, max_length=4096)


class NinjaRunResultOut(BaseModel):
    ok: bool
    ninja_device_id: int
    detail: str | None = None


__all__ = [
    "NinjaDeviceSummary",
    "NinjaRunResultOut",
    "NinjaRunScriptRequest",
    "NinjaScriptOut",
    "NinjaStatusOut",
]
