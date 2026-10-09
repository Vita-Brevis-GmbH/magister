"""Neustart und Update der ganzen Plattform aus der Konsole (ADR-0024 D5).

Vorher sass beides im Kundenportal (``/admin/system``). Gehostet hiess das:
der Admin **eines** Kunden startete den Host **aller** Kunden neu. Deshalb
steht es jetzt hier, einmal für die Plattform, und das Kundenportal hat die
Endpunkte gehostet nicht mehr.

Dasselbe Sicherheitsmodell wie vorher: die API startet nichts selbst. Sie legt
einen Auftrag als Datei in ``COCKPIT_OPS_DIR/requests/`` ab; ein Agent auf dem
Host (``scripts/plattform-ops-agent.sh``, systemd-Timer) führt ihn aus und
schreibt das Ergebnis nach ``status.json``. Der Agent kennt genau drei
Aufträge — eine übernommene Konsole kann einen Neustart bestellen, aber keinen
beliebigen Befehl auf dem Host.

Der dritte ist **„anbinden"** je Kunde: ein in der Konsole angelegter Kunde
braucht auf der Datenebene seinen DSN und seinen Kundenschlüssel, und beides
gibt die Konsole nur einmal aus und speichert es nicht. Der Agent führt dafür
``plattform-aufbau.sh kunde-anbinden <kürzel>`` aus; Schema und Daten bleiben
unberührt. Aus der Auftragsdatei liest er nur das Kürzel und prüft es gegen
dasselbe Muster wie hier.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from cockpit_api.auth import Caller, require_identity, require_person
from cockpit_api.config import settings
from cockpit_api.db import get_session
from cockpit_api.models import Tenant
from cockpit_api.models.tenant import SLUG_PATTERN, TenantStatus

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/platform/ops", tags=["platform"], dependencies=[Depends(require_identity)]
)

tenant_router = APIRouter(
    prefix="/tenants", tags=["platform"], dependencies=[Depends(require_identity)]
)

ALLOWED: tuple[str, ...] = ("restart", "update", "attach")


class OpsStatus(BaseModel):
    configured: bool
    pending: int
    last: dict[str, Any] | None
    log: str | None


class OpsRequested(BaseModel):
    id: str
    action: str
    requested_at: str
    slug: str | None = None


def _ops_dir() -> Path:
    if not settings.ops_dir:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Neustart und Update sind nicht eingerichtet (COCKPIT_OPS_DIR fehlt). "
            "Einrichten: ./scripts/plattform-aufbau.sh ops-agent",
        )
    return Path(settings.ops_dir)


def _read_status(ops: Path) -> OpsStatus:
    requests = ops / "requests"
    pending = len(list(requests.glob("*.json"))) if requests.is_dir() else 0
    last: dict[str, Any] | None = None
    try:
        raw: object = json.loads((ops / "status.json").read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            last = {str(k): v for k, v in cast(dict[object, Any], raw).items()}
    except (OSError, ValueError):
        last = None
    log: str | None
    try:
        log = (ops / "last.log").read_text(encoding="utf-8", errors="replace")[-8000:]
    except OSError:
        log = None
    return OpsStatus(configured=True, pending=pending, last=last, log=log)


def _write_request(ops: Path, payload: dict[str, Any]) -> None:
    requests = ops / "requests"
    requests.mkdir(parents=True, exist_ok=True)
    tmp = requests / f".{payload['id']}.json.tmp"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, requests / f"{payload['id']}.json")


@router.get("", response_model=OpsStatus)
async def ops_status() -> OpsStatus:
    if not settings.ops_dir:
        return OpsStatus(configured=False, pending=0, last=None, log=None)
    return await run_in_threadpool(_read_status, Path(settings.ops_dir))


@router.post("/{action}", response_model=OpsRequested, status_code=status.HTTP_202_ACCEPTED)
async def ops_request(
    action: Literal["restart", "update"],
    caller: Caller = Depends(require_person),
) -> OpsRequested:
    """Neustart oder Update bestellen. Betrifft **alle** Kunden auf dem Host."""
    ops = _ops_dir()
    payload: dict[str, Any] = {
        "id": uuid4().hex,
        "action": action,
        "requested_by": caller.actor,
        "requested_at": datetime.now(UTC).isoformat(),
    }
    await run_in_threadpool(_write_request, ops, payload)
    logger.info("Plattform-%s bestellt von %s (%s)", action, caller.actor, payload["id"])
    return OpsRequested(
        id=str(payload["id"]), action=action, requested_at=str(payload["requested_at"])
    )


#: Ab diesem Alter gilt der Zustandsbericht als veraltet. Der Ops-Agent
#: schreibt ihn einmal je Minute; drei verpasste Läufe heissen: er läuft nicht.
HEALTH_STALE_SECONDS = 180


class PlatformHealth(BaseModel):
    """Zustand des Plattform-Hosts, wie der Ops-Agent ihn zuletzt erhoben hat."""

    configured: bool
    #: Gibt es überhaupt einen Bericht? Fehlt er, läuft der Ops-Agent nicht
    #: oder ist älter als die Überwachung.
    present: bool
    age_seconds: int | None = None
    stale: bool = False
    report: dict[str, Any] | None = None
    #: Letzte Fehlermeldung der Erhebung selbst (stderr des Skripts), gekürzt.
    error: str | None = None


def _write_targets(ops: Path, targets: list[dict[str, str]]) -> None:
    tmp = ops / ".probe-targets.json.tmp"
    tmp.write_text(json.dumps(targets), encoding="utf-8")
    os.replace(tmp, ops / "probe-targets.json")


def _read_health(ops: Path) -> PlatformHealth:
    error: str | None
    try:
        error = (ops / "health.err").read_text(encoding="utf-8", errors="replace")[-2000:] or None
    except OSError:
        error = None
    path = ops / "health.json"
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        mtime = path.stat().st_mtime
    except (OSError, ValueError):
        return PlatformHealth(configured=True, present=False, error=error)
    report = (
        {str(k): v for k, v in cast(dict[object, Any], raw).items()}
        if isinstance(raw, dict)
        else None
    )
    age = int(datetime.now(UTC).timestamp() - mtime)
    return PlatformHealth(
        configured=True,
        present=report is not None,
        age_seconds=age,
        stale=age > HEALTH_STALE_SECONDS,
        report=report,
        error=error,
    )


@router.get("/health", response_model=PlatformHealth)
async def platform_health(session: AsyncSession = Depends(get_session)) -> PlatformHealth:
    """Dienste, Ports, Proben, Zertifikate und Platte des Plattform-Hosts.

    Erhoben vom Ops-Agenten auf dem Host (``scripts/plattform_zustand.py``),
    nicht von hier: die Konsole hat keinen Zugang zu Docker und zu den Ports
    des Hosts, und eine Überwachung ist kein Grund, ihr einen zu geben.

    Nebenbei legt der Aufruf die Liste der Kunden-Hostnamen für die Proben
    ab. Der Agent prüft jeden Eintrag gegen ein Hostnamen-Muster, bevor er
    ihn benutzt — die Liste kommt von hier, und hier könnte übernommen sein.
    """
    if not settings.ops_dir:
        return PlatformHealth(configured=False, present=False)
    ops = Path(settings.ops_dir)
    rows = (
        await session.execute(
            select(Tenant.slug, Tenant.hostname).where(
                Tenant.status.in_((TenantStatus.active, TenantStatus.suspended))
            )
        )
    ).all()
    targets = [{"slug": slug, "hostname": hostname} for slug, hostname in rows]
    await run_in_threadpool(_write_targets, ops, targets)
    return await run_in_threadpool(_read_health, ops)


@tenant_router.post(
    "/{tenant_id}/attach", response_model=OpsRequested, status_code=status.HTTP_202_ACCEPTED
)
async def attach_request(
    tenant_id: UUID,
    caller: Caller = Depends(require_person),
    session: AsyncSession = Depends(get_session),
) -> OpsRequested:
    """Den Kunden auf der Datenebene anbinden lassen (DSN und Schlüssel nachtragen).

    Dreht dabei das Rollenpasswort, wenn der Datenebene der DSN fehlt — ein
    neues Passwort ohne den neuen DSN daneben hiesse Ausfall, deshalb macht
    beides derselbe Agent in einem Lauf. Ein vorhandener DSN bleibt stehen.
    """
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant")
    if tenant.status not in (TenantStatus.active, TenantStatus.suspended):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Kunde steht auf {tenant.status.value}: erst die Bereitstellung abschliessen.",
        )
    if not SLUG_PATTERN.match(tenant.slug):
        # Kann aus der Datenbank nicht kommen (geprüft beim Anlegen); der Agent
        # prüft trotzdem ein zweites Mal.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ungültiges Kürzel")
    ops = _ops_dir()
    payload: dict[str, Any] = {
        "id": uuid4().hex,
        "action": "attach",
        "slug": tenant.slug,
        "requested_by": caller.actor,
        "requested_at": datetime.now(UTC).isoformat(),
    }
    await run_in_threadpool(_write_request, ops, payload)
    logger.info("Anbinden von %s bestellt von %s (%s)", tenant.slug, caller.actor, payload["id"])
    return OpsRequested(
        id=str(payload["id"]),
        action="attach",
        requested_at=str(payload["requested_at"]),
        slug=tenant.slug,
    )


__all__ = ["ALLOWED", "HEALTH_STALE_SECONDS", "router", "tenant_router"]
