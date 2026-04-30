"""FastAPI dependencies that resolve the current authenticated user."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.models.auth import RoleAssignment
from magister_api.repositories.auth import RoleAssignmentRepository, SessionRepository
from magister_api.repositories.base import ScopeContext


@dataclass(frozen=True)
class AuthenticatedUser:
    """Resolved view of the user behind the current session cookie."""

    ad_object_guid: str
    upn: str
    is_admin: bool
    school_scope: tuple[int, ...]
    roles: tuple[str, ...]
    expires_at: object  # datetime, kept untyped to avoid an import cycle in dataclasses

    def to_scope(self) -> ScopeContext:
        return ScopeContext(
            ad_object_guid=self.ad_object_guid,
            upn=self.upn,
            is_admin=self.is_admin,
            school_scope=self.school_scope,
            roles=self.roles,
        )


def _roles_to_user(
    *,
    ad_object_guid: str,
    upn: str,
    role_rows: list[RoleAssignment],
    expires_at: object,
) -> AuthenticatedUser:
    roles: list[str] = []
    schools: set[int] = set()
    is_admin = False
    for r in role_rows:
        roles.append(r.role)
        if r.role == "admin":
            is_admin = True
        elif r.role == "schulleitung" and r.school_id is not None:
            schools.add(r.school_id)
    return AuthenticatedUser(
        ad_object_guid=ad_object_guid,
        upn=upn,
        is_admin=is_admin,
        school_scope=tuple(sorted(schools)),
        roles=tuple(roles),
        expires_at=expires_at,
    )


async def get_optional_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser | None:
    """Return the user if a valid session cookie is present, else ``None``."""
    cookie = request.cookies.get(settings.session_cookie_name)
    if not cookie:
        return None

    sessions_repo = SessionRepository(session)
    sess = await sessions_repo.get(cookie)
    if sess is None:
        return None

    # Reject expired sessions.
    from magister_api.models.base import utcnow

    if sess.expires_at <= utcnow():
        await sessions_repo.delete(cookie)
        return None

    # Sliding refresh — flush only; the session-per-request wrapper commits.
    await sessions_repo.touch(cookie, timedelta(minutes=settings.session_lifetime_minutes))

    role_rows = await RoleAssignmentRepository(session).list_active_for(sess.ad_object_guid)
    # Resolve the user's UPN from ad_user_cache (always present once a session exists).
    from magister_api.models.auth import AdUserCache

    cache_row = await session.get(AdUserCache, sess.ad_object_guid)
    upn = cache_row.upn if cache_row is not None else ""
    return _roles_to_user(
        ad_object_guid=sess.ad_object_guid,
        upn=upn,
        role_rows=role_rows,
        expires_at=sess.expires_at,
    )


async def get_current_user(
    user: AuthenticatedUser | None = Depends(get_optional_user),
) -> AuthenticatedUser:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthenticated")
    return user
