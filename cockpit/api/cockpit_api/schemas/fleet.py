"""Schemata für die Flotten-Befunde (ADR-0021 D6)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from cockpit_api.services.fleet import Severity


class FleetFindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    #: Maschinenlesbar — die Oberfläche gruppiert danach, und ein
    #: Überwachungssystem kann einzelne Arten ausblenden.
    kind: str
    severity: Severity
    tenant_slug: str
    agent_name: str | None
    #: Für Menschen, mit dem nächsten Schritt darin. Ein Befund ohne „und was
    #: nun“ ist eine Zeile, die man wegklickt.
    detail: str


class FleetReportOut(BaseModel):
    findings: list[FleetFindingOut]
    #: Derselbe Wert, den das CLI als Exit-Code zurückgibt: 0 in Ordnung,
    #: 1 Warnung, 2 kritisch. Damit muss die Oberfläche den Schweregrad nicht
    #: selbst aus der Liste rechnen — und rechnet ihn nicht anders als das CLI.
    worst: int


__all__ = ["FleetFindingOut", "FleetReportOut"]
