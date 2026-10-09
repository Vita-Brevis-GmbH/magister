"""`/api/fleet/findings` — was an der Flotte jemand ansehen muss (ADR-0021 D6).

Nur lesend, und absichtlich ohne Zustand: die Befunde werden bei jeder Anfrage
gerechnet und nirgends gespeichert. Ein gespeicherter Befund müsste
quittiert, aufgeräumt und synchron gehalten werden — und wäre spätestens
dann falsch, wenn sich der Agent wieder gemeldet hat.

Kein `require_person`: das liest die Oberfläche, und es liest ein
Überwachungssystem über den Exit-Code des CLI. Beides ist keine Person.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import require_identity
from cockpit_api.db import get_session
from cockpit_api.schemas.fleet import FleetFindingOut, FleetReportOut
from cockpit_api.services.fleet import exit_code, fleet_findings

router = APIRouter(prefix="/fleet", tags=["fleet"], dependencies=[Depends(require_identity)])


@router.get("/findings", response_model=FleetReportOut)
async def findings(session: AsyncSession = Depends(get_session)) -> FleetReportOut:
    found = await fleet_findings(session)
    return FleetReportOut(
        findings=[FleetFindingOut.model_validate(f, from_attributes=True) for f in found],
        worst=exit_code(found),
    )


__all__ = ["router"]
