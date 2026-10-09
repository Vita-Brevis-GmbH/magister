"""`/api/tenants/{id}/operator-access` — Zugriff auf einen Kunden öffnen (ADR-0019).

Die Konsole stellt einen **Einlöseschein** aus und keine Sitzung. Sie hat zum
Kundenschema keinen Zugang, und die Sitzung gehört dorthin, wo sie geprüft wird.

Der Grund ist Pflicht (ADR-0019 D7) und reist signiert mit: die Datenebene
schreibt ihn unverändert in das Protokoll des Kunden.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import Caller, require_identity, require_person
from cockpit_api.config import settings
from cockpit_api.db import get_session
from cockpit_api.models import Tenant
from cockpit_api.schemas.operator_access import (
    OperatorAccessGrantOut,
    OperatorAccessOut,
    OperatorAccessRequest,
)
from cockpit_api.services.operator_access import OperatorAccessError, OperatorAccessService

logger = logging.getLogger(__name__)

# Boden am Router, Erhöhung beim Ausstellen (ADR-0020 D4). Der Name des
# Operators reist signiert mit und landet im Audit des Kunden — er kommt
# deshalb aus der Sitzung und nicht aus dem Anfragekörper.
router = APIRouter(
    prefix="/tenants/{tenant_id}",
    tags=["operator-access"],
    dependencies=[Depends(require_identity)],
)


async def _known_tenant(session: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant")
    return tenant


@router.post("/operator-access", response_model=OperatorAccessOut)
async def open_operator_access(
    tenant_id: UUID,
    body: OperatorAccessRequest,
    caller: Caller = Depends(require_person),
    session: AsyncSession = Depends(get_session),
) -> OperatorAccessOut:
    tenant = await _known_tenant(session, tenant_id)
    svc = OperatorAccessService(session)
    try:
        assertion, grant = await svc.issue(
            tenant,
            operator=caller.actor,
            reason=body.reason,
            ticket=body.ticket,
            signing_key_path=settings.operator_signing_key,
        )
    except OperatorAccessError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await session.commit()
    # Der Grund steht im Log, die Assertion nicht: sie ist ein Zugangsmittel.
    logger.info(
        "Operator-Zugriff auf %s ausgestellt für %s (Ticket %s): %s",
        tenant.slug,
        caller.actor,
        grant.ticket or "—",
        grant.reason,
    )
    return OperatorAccessOut(
        jti=str(grant.jti),
        assertion=assertion,
        expires_at=grant.expires_at,
        redeem_url=f"https://{tenant.hostname}/operator/redeem#{assertion}",
    )


@router.get("/operator-access", response_model=list[OperatorAccessGrantOut])
async def list_operator_access(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[OperatorAccessGrantOut]:
    """Was die Konsole ausgestellt hat — nicht, was eingelöst wurde.

    Der Unterschied ist die Auskunft: eine ausgestellte und nicht eingelöste
    Assertion sieht man nur hier. Ob ein Zugriff stattgefunden hat, steht im
    Protokoll des Kunden (ADR-0019 D4).
    """
    await _known_tenant(session, tenant_id)
    rows = await OperatorAccessService(session).history(tenant_id)
    return [
        OperatorAccessGrantOut(
            jti=str(row.jti),
            operator=row.operator,
            reason=row.reason,
            ticket=row.ticket,
            issued_at=row.issued_at,
            expires_at=row.expires_at,
        )
        for row in rows
    ]


__all__ = ["router"]
