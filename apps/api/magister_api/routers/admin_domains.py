"""``/admin/domains`` — Mail- und UPN-Domains für die Auswahl im Benutzerformular.

Gehört dem Kunden, auch gehostet (immer gemountet): welche Domains seine
Konten tragen dürfen, weiss er, nicht der Betreiber. Seit 2026-10 setzt die
Konsole ``mail_domains`` nicht mehr.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.app_settings import AppSettingsUpdate
from magister_api.services.app_settings import AppSettingsService
from magister_api.services.upn_domains import mail_domains_in_use, upn_domains

router = APIRouter(prefix="/admin/domains", tags=["admin"])


class DomainsOut(BaseModel):
    #: Für Mailadresse und UPN.
    mail_domains: list[str]
    #: Zusätzlich nur für den UPN.
    upn_domains: list[str]
    #: Was die UPN-Auswahl tatsächlich anbietet — inklusive dessen, was das
    #: AD kennt (DNS-Name der Domäne, Suffixe vorhandener Konten).
    upn_choices: list[str]
    #: Domains der Mailadressen im AD, die noch keine Mail-Domain sind —
    #: Vorschläge zum Übernehmen.
    mail_suggestions: list[str] = Field(default_factory=list)


class DomainsIn(BaseModel):
    mail_domains: list[str] = Field(max_length=50)
    upn_domains: list[str] = Field(max_length=50)


async def _out(session: AsyncSession, settings: Settings) -> DomainsOut:
    eff = await AppSettingsService(session, settings).get_effective()
    return DomainsOut(
        mail_domains=list(eff.mail_domains),
        upn_domains=list(eff.upn_domains),
        upn_choices=await upn_domains(
            session,
            mail_domains=eff.mail_domains,
            users_search_base=eff.ad_users_search_base,
            extra=eff.upn_domains,
        ),
        mail_suggestions=[
            d for d in await mail_domains_in_use(session) if d not in eff.mail_domains
        ],
    )


@router.get("", response_model=DomainsOut)
async def get_domains(
    user: AuthenticatedUser = Depends(require_admin),  # noqa: ARG001
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> DomainsOut:
    return await _out(session, settings)


@router.put("", response_model=DomainsOut)
async def put_domains(
    request: Request,
    body: DomainsIn,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> DomainsOut:
    # Validierung (Format, Kleinschreibung, Doppelte) im selben Schema wie das
    # Formular der Einzelinstallation — ein 422 nennt die falsche Domain.
    try:
        payload = AppSettingsUpdate(mail_domains=body.mail_domains, upn_domains=body.upn_domains)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise HTTPException(status_code=422, detail=str(first.get("msg", ""))) from exc
    ip, request_id = _ip_request_id(request)
    await AppSettingsService(session, settings).update(
        payload,
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        ip=ip,
        request_id=request_id,
        action="domains_updated",
    )
    return await _out(session, settings)


__all__ = ["router"]
