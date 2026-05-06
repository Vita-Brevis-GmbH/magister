"""Shared helpers for integration tests that need an authenticated session.

The bootstrap-OIDC flow lives in ``test_auth_flow.py``; everything else just
seeds a session row and a CSRF token directly so the test focus stays on
the resource under test.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.csrf import issue_csrf_token
from magister_api.auth.sessions import new_session_id
from magister_api.config import Settings
from magister_api.models.auth import AdUserCache, RoleAssignment, Session
from magister_api.models.base import utcnow


async def seed_user_with_session(
    *,
    session: AsyncSession,
    settings: Settings,
    upn: str,
    ad_object_guid: str,
    school_id: int | None,
    kind: str,
    role: str | None = None,
    role_school_id: int | None = None,
) -> tuple[str, str]:
    """Insert ad_user_cache + optional role + a fresh session.

    Returns ``(session_id, csrf_token)``.
    """
    cache = AdUserCache(
        ad_object_guid=ad_object_guid,
        school_id=school_id,
        upn=upn,
        given_name=None,
        surname=None,
        kind=kind,
        enabled=True,
        last_sync_at=None,
        ms_ds_consistency_guid=ad_object_guid,
    )
    session.add(cache)
    if role:
        session.add(
            RoleAssignment(
                ad_object_guid=ad_object_guid,
                role=role,
                school_id=role_school_id,
                granted_by="test",
            )
        )
    sid = new_session_id()
    now = utcnow()
    session.add(
        Session(
            id=sid,
            ad_object_guid=ad_object_guid,
            oidc_subject=f"oidc-sub-{ad_object_guid[:8]}",
            expires_at=now + timedelta(minutes=settings.session_lifetime_minutes),
            last_seen_at=now,
            ip=None,
            user_agent="pytest",
            created_at=now,
        )
    )
    await session.flush()
    return sid, issue_csrf_token(sid, settings)
