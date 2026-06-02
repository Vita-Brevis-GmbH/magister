from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.config import settings
from cockpit_api.db import get_session
from cockpit_api.models import ServiceToken


def _extract_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    return authorization.removeprefix("Bearer ").strip()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def require_bootstrap_token(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Accept either the legacy bootstrap token or a non-revoked, non-expired
    service token (hardening-audit M-01).

    The bootstrap token stays as a break-glass admin credential — it is the
    only way to create the first service token after a fresh deployment.
    All operational callers (UI, runner) should switch to service tokens
    with explicit ``expires_at``.
    """
    token = _extract_token(authorization)
    if secrets.compare_digest(token, settings.bootstrap_token):
        return

    digest = hash_token(token)
    stmt = select(ServiceToken).where(ServiceToken.token_hash == digest)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None or row.revoked or row.expires_at < datetime.now(UTC):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid token")
    row.last_used_at = datetime.now(UTC)
    await session.commit()
