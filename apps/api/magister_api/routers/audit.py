"""``/audit`` — filtered, paginated, decrypted view of ``audit_events``.

Per CLAUDE.md "Immer"-Regel: payloads are decrypted via ``AuditService``,
never via raw ``SELECT payload``. Schul-Scope:

- Admin: no implicit filter; ``school_id`` query-param narrows. Sees
  ``school_id IS NULL`` rows too.
- Schulleitung / SMI: hard-restricted to ``school_id IN user.school_scope``;
  ``school_id IS NULL`` rows are excluded.
- KL: not on the tier (require_role 403s).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditFilter, AuditService
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_role
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.schemas.audit import AuditEventListResponse, AuditEventOut

router = APIRouter(prefix="/audit", tags=["audit"])

require_audit_reader = require_role("schulleitung", "smi")


@router.get("/events", response_model=AuditEventListResponse)
async def list_audit_events(
    user: AuthenticatedUser = Depends(require_audit_reader),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    action: Annotated[str | None, Query(max_length=64)] = None,
    target_kind: Annotated[str | None, Query(max_length=64)] = None,
    target_id: Annotated[str | None, Query(max_length=128)] = None,
    actor_upn: Annotated[
        str | None,
        Query(min_length=1, max_length=320, description="Substring, case-insensitive."),
    ] = None,
    from_ts: Annotated[datetime | None, Query(description="Inclusive lower bound.")] = None,
    to_ts: Annotated[datetime | None, Query(description="Inclusive upper bound.")] = None,
    school_id: Annotated[
        int | None,
        Query(description="Admin-only narrow-by-school filter. Ignored for non-admin."),
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditEventListResponse:
    if user.is_admin:
        # Admin may either see everything (None) or narrow to one school.
        school_ids: list[int] | None = [school_id] if school_id is not None else None
    else:
        # Non-admin: hard scope to their schools. The optional school_id param
        # may further narrow within scope, but must not widen.
        if school_id is not None:
            if school_id not in user.school_scope:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
            school_ids = [school_id]
        else:
            school_ids = list(user.school_scope)

    listing = await AuditService(session, settings).list(
        filter=AuditFilter(
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            actor_upn=actor_upn,
            from_ts=from_ts,
            to_ts=to_ts,
            school_ids=school_ids,
        ),
        offset=offset,
        limit=limit,
    )

    return AuditEventListResponse(
        items=[AuditEventOut.model_validate(record) for record in listing.items],
        total=listing.total,
        offset=offset,
        limit=limit,
    )


__all__ = ["router"]
