"""``/password-expiry`` — wessen Passwort bald abläuft, und wer keine Mailadresse hat.

Lesen, im Sichtbereich der Person (Schul-Scope). Für die Erinnerung selbst
siehe :mod:`magister_api.services.password_expiry`.
"""

from __future__ import annotations

import math
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.capabilities import Capability, require_capability
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.mail import mail_config_from
from magister_api.models.auth import AdUserCache
from magister_api.models.base import utcnow
from magister_api.repositories.password_expiry import PasswordExpiryRepository
from magister_api.schemas.password_expiry import PasswordExpiryOverview, PasswordExpiryRow
from magister_api.services.app_settings import AppSettingsService

router = APIRouter(prefix="/password-expiry", tags=["users"])

require_reader = require_capability(Capability.USER_READ)  # admin + schulleitung + smi


@router.get("", response_model=PasswordExpiryOverview)
async def password_expiry_overview(
    view: Literal["expiring", "no_mail"] = Query(default="expiring"),
    days: int = Query(default=14, ge=1, le=90),
    school_id: int | None = Query(default=None),
    user: AuthenticatedUser = Depends(require_reader),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> PasswordExpiryOverview:
    now = utcnow()
    repo = PasswordExpiryRepository(session, user.to_scope())
    if view == "expiring":
        found = await repo.expiring(now=now, within_days=days, school_id=school_id)
    else:
        found = await repo.without_mail(school_id=school_id)
    notices = await repo.last_notices([u for u, _ in found])
    rows: list[PasswordExpiryRow] = []
    for u, tpl_name in found:
        left = (
            math.ceil((u.password_expires_at - now).total_seconds() / 86400)
            if u.password_expires_at and not u.password_never_expires
            else None
        )
        notice = notices.get(u.ad_object_guid)
        rows.append(
            PasswordExpiryRow(
                ad_object_guid=u.ad_object_guid,
                display_name=u.display_name,
                given_name=u.given_name,
                surname=u.surname,
                upn=u.upn,
                kind=u.kind,
                school_id=u.school_id,
                jahrgangsstufe=u.jahrgangsstufe,
                group_template_name=tpl_name,
                mail=u.mail or None,
                password_expires_at=None if u.password_never_expires else u.password_expires_at,
                days_left=left,
                notice_status=notice.status if notice else None,
                notice_at=notice.created_at if notice else None,
                notice_threshold_days=notice.threshold_days if notice else None,
            )
        )
    eff = await AppSettingsService(session, settings).get_effective()
    # scope-bypass: nur ein Zeitstempel (max) über den Cache, keine Personendaten.
    info_as_of = (await session.execute(select(func.max(AdUserCache.password_info_at)))).scalar()
    return PasswordExpiryOverview(
        view=view,
        within_days=days,
        rows=rows,
        notice_enabled=eff.expiry_notice_enabled,
        mail_ready=not mail_config_from(eff).missing(),
        info_as_of=info_as_of,
    )


__all__ = ["router"]
