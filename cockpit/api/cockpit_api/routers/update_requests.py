from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import require_bootstrap_token
from cockpit_api.db import get_session
from cockpit_api.models import Instance, UpdateRequest, UpdateRequestStatus
from cockpit_api.schemas.update_request import (
    UpdateRequestCreate,
    UpdateRequestFail,
    UpdateRequestOut,
    UpdateRequestRunnerOut,
)

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


@router.get("/next", response_model=UpdateRequestRunnerOut | None)
async def next_pending(
    session: AsyncSession = Depends(get_session),
) -> UpdateRequestRunnerOut | None:
    """Runner endpoint: returns the oldest pending request, atomically claims it."""
    stmt = (
        select(UpdateRequest)
        .where(UpdateRequest.status == UpdateRequestStatus.pending)
        .order_by(UpdateRequest.requested_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    req = (await session.execute(stmt)).scalar_one_or_none()
    if req is None:
        return None
    req.status = UpdateRequestStatus.in_progress
    inst = await session.get(Instance, req.instance_id)
    await session.commit()
    await session.refresh(req)
    return UpdateRequestRunnerOut(
        id=req.id,
        instance_id=req.instance_id,
        instance_slug=inst.slug if inst else "",
        instance_base_url=inst.base_url if inst else "",
        instance_channel=inst.channel.value if inst else "stable",
        target_version=req.target_version,
        status=req.status,
        requested_at=req.requested_at,
    )


@router.post("/{request_id}/complete", response_model=UpdateRequestOut)
async def complete_update_request(
    request_id: UUID, session: AsyncSession = Depends(get_session)
) -> UpdateRequest:
    req = await session.get(UpdateRequest, request_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if req.status is not UpdateRequestStatus.in_progress:
        raise HTTPException(status.HTTP_409_CONFLICT, "only in_progress requests can complete")
    req.status = UpdateRequestStatus.completed
    req.completed_at = datetime.now(UTC)
    inst = await session.get(Instance, req.instance_id)
    if inst is not None:
        inst.deployed_version = req.target_version
    await session.commit()
    await session.refresh(req)
    return req


@router.post("/{request_id}/fail", response_model=UpdateRequestOut)
async def fail_update_request(
    request_id: UUID,
    payload: UpdateRequestFail,
    session: AsyncSession = Depends(get_session),
) -> UpdateRequest:
    req = await session.get(UpdateRequest, request_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if req.status is not UpdateRequestStatus.in_progress:
        raise HTTPException(status.HTTP_409_CONFLICT, "only in_progress requests can fail")
    req.status = UpdateRequestStatus.failed
    req.completed_at = datetime.now(UTC)
    req.last_error = payload.error[:1000]
    await session.commit()
    await session.refresh(req)
    return req
