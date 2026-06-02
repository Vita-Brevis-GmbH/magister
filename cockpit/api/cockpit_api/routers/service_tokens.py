from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import hash_token, require_bootstrap_token
from cockpit_api.db import get_session
from cockpit_api.models import ServiceToken

router = APIRouter(
    prefix="/service-tokens",
    tags=["service-tokens"],
    dependencies=[Depends(require_bootstrap_token)],
)


class ServiceTokenCreate(BaseModel):
    description: str
    ttl_days: int = 90


class ServiceTokenIssued(BaseModel):
    id: UUID
    description: str
    expires_at: datetime
    token: str  # only returned once, at creation


class ServiceTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    description: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked: bool


@router.get("", response_model=list[ServiceTokenOut])
async def list_tokens(session: AsyncSession = Depends(get_session)) -> list[ServiceToken]:
    stmt = select(ServiceToken).order_by(ServiceToken.created_at.desc())
    return list((await session.execute(stmt)).scalars())


@router.post("", response_model=ServiceTokenIssued, status_code=status.HTTP_201_CREATED)
async def create_token(
    payload: ServiceTokenCreate, session: AsyncSession = Depends(get_session)
) -> ServiceTokenIssued:
    if payload.ttl_days <= 0 or payload.ttl_days > 365:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ttl_days must be 1..365")
    raw = secrets.token_urlsafe(40)
    row = ServiceToken(
        token_hash=hash_token(raw),
        description=payload.description[:200],
        expires_at=datetime.now(UTC) + timedelta(days=payload.ttl_days),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ServiceTokenIssued(
        id=row.id, description=row.description, expires_at=row.expires_at, token=raw
    )


@router.post("/{token_id}/revoke", response_model=ServiceTokenOut)
async def revoke_token(
    token_id: UUID, session: AsyncSession = Depends(get_session)
) -> ServiceToken:
    row = await session.get(ServiceToken, token_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    row.revoked = True
    await session.commit()
    await session.refresh(row)
    return row
