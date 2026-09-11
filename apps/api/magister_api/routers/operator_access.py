"""`/operator` — Einlösen und Sichtbarkeit eines Operator-Zugriffs (ADR-0019).

Zwei Flächen mit zwei sehr verschiedenen Zugängen:

* `POST /operator/redeem` ist **unauthentisiert**. Der Einlöseschein ist das
  Zugangsmittel; wer ihn hat, bekommt die Sitzung. Er ist signiert, einmal
  verwendbar und sechzig Sekunden gültig.
* `GET /operator/accesses` ist für den **Kunden**. Jeder angemeldete Benutzer
  darf sie sehen — nicht nur Admins. Eine Transparenz, die nur derjenige sieht,
  der den Zugriff ohnehin bewilligt hätte, ist keine (ADR-0019 D6).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.csrf import issue_csrf_token
from magister_api.auth.current_user import AuthenticatedUser, get_current_user
from magister_api.auth.operator_assertion import OperatorAssertionError
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.operator_access import (
    OperatorAccessOut,
    OperatorRedeemOut,
    OperatorRedeemRequest,
)
from magister_api.services.operator_access import OperatorAccessService
from magister_api.tenancy.context import tenant_from_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/operator", tags=["operator"])


@router.post("/redeem", response_model=OperatorRedeemOut)
async def redeem(
    request: Request,
    response: Response,
    payload: OperatorRedeemRequest,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> OperatorRedeemOut:
    """Einlöseschein gegen eine befristete Sitzung tauschen.

    Jede Ablehnung ist ein 403 mit derselben Kennung nach aussen
    (`operator_assertion_invalid`) — abgelaufen, doppelt eingelöst, falscher
    Kunde oder falsche Signatur sind für den Vorleger dasselbe. Der Grund steht
    im Log des Betreibers, wo er hingehört: eine Antwort, die „bereits
    verbraucht" von „falsche Signatur" unterscheidet, verrät, welcher Wert
    einmal gültig war.
    """
    tenant = tenant_from_request(request)
    ip, request_id = _ip_request_id(request)
    svc = OperatorAccessService(session, settings)
    try:
        redeemed = await svc.redeem(
            payload.assertion,
            tenant_slug=tenant.slug,
            ip=ip,
            user_agent=request.headers.get("user-agent", "")[:512] or None,
            request_id=request_id,
        )
    except OperatorAssertionError as exc:
        logger.warning("Operator-Einlösung bei %s abgewiesen: %s", tenant.slug, exc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="operator_assertion_invalid"
        ) from exc

    response.set_cookie(
        key=settings.session_cookie_name,
        value=redeemed.session_id,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=issue_csrf_token(redeemed.session_id, settings),
        httponly=False,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )
    return OperatorRedeemOut(
        operator=redeemed.assertion.operator,
        reason=redeemed.assertion.reason,
        ticket=redeemed.assertion.ticket,
        expires_at=redeemed.access.expires_at,
    )


@router.get("/accesses", response_model=list[OperatorAccessOut])
async def list_accesses(
    user: AuthenticatedUser = Depends(get_current_user),  # noqa: ARG001
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[OperatorAccessOut]:
    """Wann Vita Brevis hier drin war, und warum.

    Ausdrücklich ohne Capability-Prüfung: jeder angemeldete Benutzer des Kunden
    darf das sehen (ADR-0019 D6). Die Liste enthält keine Personendaten des
    Kunden — nur wer von aussen zugesehen hat.
    """
    rows = await OperatorAccessService(session, settings).history()
    return [
        OperatorAccessOut(
            jti=str(row.jti),
            operator=row.operator_upn,
            reason=row.reason,
            ticket=row.ticket,
            started_at=row.started_at,
            expires_at=row.expires_at,
            ended_at=row.ended_at,
        )
        for row in rows
    ]


__all__ = ["router"]
