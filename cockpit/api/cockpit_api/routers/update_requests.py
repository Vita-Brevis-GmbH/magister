from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import require_bootstrap_token
from cockpit_api.db import get_session
from cockpit_api.models import Instance, UpdateRequest, UpdateRequestStatus
from cockpit_api.schemas.update_request import UpdateRequestCreate, UpdateRequestOut

router = APIRouter(
    prefix="/update-requests",
    tags=["update-requests"],
    dependencies=[Depends(require_bootstrap_token)],
)


@router.get("", response_model=list[UpdateRequestOut])
async def list_update_requests(
    instance_id: UUID | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[UpdateRequest]:
    stmt = select(UpdateRequest).order_by(UpdateRequest.requested_at.desc())
    if instance_id is not None:
        stmt = stmt.where(UpdateRequest.instance_id == instance_id)
    return list((await session.execute(stmt)).scalars())


@router.post(
    "/instance/{instance_id}",
    response_model=UpdateRequestOut,
    status_code=status.HTTP_201_CREATED,
)
async def request_update(
    instance_id: UUID,
    payload: UpdateRequestCreate,
    session: AsyncSession = Depends(get_session),
) -> UpdateRequest:
    inst = await session.get(Instance, instance_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "instance not found")
    target = payload.target_version or inst.latest_available_version
    if not target:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "no target_version available (release manifest not yet fetched)",
        )
    if target == inst.deployed_version:
        raise HTTPException(status.HTTP_409_CONFLICT, "instance already on target version")
    req = UpdateRequest(
        instance_id=instance_id,
        target_version=target,
        note=payload.note,
        status=UpdateRequestStatus.pending,
    )
    session.add(req)
    await session.commit()
    await session.refresh(req)
    return req


@router.post("/{request_id}/cancel", response_model=UpdateRequestOut)
async def cancel_update_request(
    request_id: UUID, session: AsyncSession = Depends(get_session)
) -> UpdateRequest:
    req = await session.get(UpdateRequest, request_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if req.status is not UpdateRequestStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "only pending requests can be cancelled")
    req.status = UpdateRequestStatus.cancelled
    await session.commit()
    await session.refresh(req)
    return req
