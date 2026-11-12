"""`/api/health/stack` — was die Überwachung des Betreibers liest.

`/api/health` (in `main.py`) bleibt die flache Sonde für den Container: sie
darf nichts anfassen, was ausfallen kann, sonst startet ein Orchestrierer den
Prozess neu, weil die Datenbank hustet.

Diese Route ist das Gegenteil: sie fasst genau das an, was ausfallen kann, und
sagt es in einer Zahl (0/1/2 wie `fleet_check`, ADR-0021 D6) plus einer Liste
für den Menschen, der danach hinsieht.

Keine Anmeldung, wie bei der flachen Sonde — aber dieselbe Lage: hinter dem
Management-Listener, also hinter interner Adresse, Client-Zertifikat und
Marker (`docs/runbooks/console-listener.md`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.db import get_session
from cockpit_api.services.stack_health import stack_health

router = APIRouter(prefix="/health", tags=["meta"])


@router.get("")
async def health() -> dict[str, str]:
    """Die flache Sonde: lebt der Prozess?

    Sie fasst absichtlich nichts an, was ausfallen kann. Eine Sonde, die die
    Datenbank prüft, lässt einen Orchestrierer den Prozess neu starten, weil
    die Datenbank hustet — und der Neustart hilft dagegen nicht.
    """
    return {"status": "ok"}


@router.get("/stack")
async def health_stack(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    """Immer HTTP 200, solange die Anwendung antwortet.

    Der Zustand steht im Rumpf: ein Sensor, der schon am Statuscode
    scheitert, liest die Begründung nicht mehr — und genau sie ist der Zweck
    dieser Route.
    """
    return (await stack_health(session)).as_dict()


__all__ = ["router"]
