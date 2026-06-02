import secrets

from fastapi import Header, HTTPException, status

from cockpit_api.config import settings


async def require_bootstrap_token(
    authorization: str | None = Header(default=None),
) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, settings.bootstrap_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid token")
