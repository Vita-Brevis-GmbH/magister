from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cockpit_api.auth import require_bootstrap_token
from cockpit_api.db import get_session
from cockpit_api.models import Instance
from cockpit_api.schemas.instance import InstanceCreate, InstanceOut, InstanceUpdate
from cockpit_api.services.health_poller import poll_instance

router = APIRouter(
    prefix="/instances", tags=["instances"], dependencies=[Depends(require_bootstrap_token)]
)


@router.get("", response_model=list[InstanceOut])
async def list_instances(session: AsyncSession = Depends(get_session)) -> list[Instance]:
    result = await session.execute(select(Instance).order_by(Instance.slug))
    return list(result.scalars())


@router.post("", response_model=InstanceOut, status_code=status.HTTP_201_CREATED)
async def create_instance(
    payload: InstanceCreate, session: AsyncSession = Depends(get_session)
) -> Instance:
    inst = Instance(
        slug=payload.slug,
        display_name=payload.display_name,
        base_url=str(payload.base_url),
        channel=payload.channel,
    )
    session.add(inst)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "slug already exists") from e
    await session.refresh(inst)
    return inst


@router.get("/{instance_id}", response_model=InstanceOut)
async def get_instance(instance_id: UUID, session: AsyncSession = Depends(get_session)) -> Instance:
    inst = await session.get(Instance, instance_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return inst


@router.patch("/{instance_id}", response_model=InstanceOut)
async def update_instance(
    instance_id: UUID,
    payload: InstanceUpdate,
    session: AsyncSession = Depends(get_session),
) -> Instance:
    inst = await session.get(Instance, instance_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if payload.display_name is not None:
        inst.display_name = payload.display_name
    if payload.base_url is not None:
        inst.base_url = str(payload.base_url)
    if payload.channel is not None:
        inst.channel = payload.channel
    await session.commit()
    await session.refresh(inst)
    return inst


@router.delete("/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_instance(instance_id: UUID, session: AsyncSession = Depends(get_session)) -> None:
    inst = await session.get(Instance, instance_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    await session.delete(inst)
    await session.commit()


@router.post("/{instance_id}/poll", response_model=InstanceOut)
async def poll_now(instance_id: UUID, session: AsyncSession = Depends(get_session)) -> Instance:
    inst = await session.get(Instance, instance_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    async with httpx.AsyncClient() as client:
        await poll_instance(client, inst)
    await session.commit()
    await session.refresh(inst)
    return inst
