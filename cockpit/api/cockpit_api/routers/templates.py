"""`/api/platform/templates` — die globalen Vorlagen pflegen (ADR-0018).

Nur der Betreiber. Die Kunden-Seite dieser Sache ist der Soll-Zustand, den die
Datenebene abholt; geschrieben wird ausschliesslich hier.

Ein `key`/`language`-Paar ist der Schlüssel und steht im Pfad. Deshalb `PUT`
und kein `POST`: dieselbe Anfrage zweimal geschickt ergibt denselben Zustand,
und die Versionszählung bleibt bei eins, weil sich nichts geändert hat.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import Caller, require_identity, require_person
from cockpit_api.db import get_session
from cockpit_api.models.template import PlatformTemplate
from cockpit_api.schemas.templates import (
    PlatformTemplateListOut,
    PlatformTemplateOut,
    PlatformTemplateSave,
)
from cockpit_api.services.templates import (
    LANGUAGES,
    TEMPLATE_KEYS,
    TemplateError,
    TemplateService,
)

logger = logging.getLogger(__name__)

# Boden am Router, Erhöhung an den schreibenden Routen (ADR-0020 D4).
router = APIRouter(
    prefix="/platform/templates",
    tags=["templates"],
    dependencies=[Depends(require_identity)],
)


async def _out(svc: TemplateService, row: PlatformTemplate) -> PlatformTemplateOut:
    out = PlatformTemplateOut.model_validate(row)
    return out.model_copy(update={"tenant_ids": await svc.tenant_ids(row.id)})


@router.get("", response_model=PlatformTemplateListOut)
async def list_templates(
    session: AsyncSession = Depends(get_session),
) -> PlatformTemplateListOut:
    svc = TemplateService(session)
    rows = await svc.list_all()
    return PlatformTemplateListOut(
        items=[await _out(svc, row) for row in rows],
        keys=sorted(TEMPLATE_KEYS),
        languages=sorted(LANGUAGES),
    )


@router.put("/{key}/{language}", response_model=PlatformTemplateOut)
async def put_template(
    key: str,
    language: str,
    body: PlatformTemplateSave,
    caller: Caller = Depends(require_person),
    session: AsyncSession = Depends(get_session),
) -> PlatformTemplateOut:
    svc = TemplateService(session)
    try:
        row = await svc.save(
            key=key,
            language=language,
            subject=body.subject,
            body_html=body.body_html,
            may_override=body.may_override,
            audience=body.audience,
            audience_profile=body.audience_profile,
            tenant_ids=body.tenant_ids,
            is_active=body.is_active,
            actor=caller.actor,
        )
    except TemplateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    out = await _out(svc, row)
    await session.commit()
    logger.info(
        "Globale Vorlage %s/%s gespeichert von %s (Fassung %d, %s)",
        key,
        language,
        caller.actor,
        row.version,
        "gesperrt" if not row.may_override else "überschreibbar",
    )
    return out


@router.delete("/{key}/{language}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    key: str,
    language: str,
    caller: Caller = Depends(require_person),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Die Vorlage ganz entfernen.

    Beim nächsten Abgleich verschwindet sie aus dem Kundenschema (ADR-0018 D6)
    — der eigene Text des Kunden bleibt, weil er in einer anderen Tabelle
    steht (D2). Wer eine Vorlage nur vorübergehend zurückziehen will, schaltet
    sie aus; das behält die Fassungsnummer und damit die Quittungen.
    """
    if not await TemplateService(session).delete(key, language):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown template")
    await session.commit()
    logger.info("Globale Vorlage %s/%s entfernt", key, language)


__all__ = ["router"]
