"""``/devices`` router — Magister-managed device inventory. Admin or SMI only.

- GET    /devices           — list devices in scope (+ free pool)
- POST   /devices           — create a manual device
- GET    /devices/{id}      — single device
- PATCH  /devices/{id}      — edit attributes (name/type/serial/notes)
- POST   /devices/{id}/assign — bind to person/class/school or free
- DELETE /devices/{id}      — remove a device
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_smi
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.devices import (
    DeviceAssign,
    DeviceCreate,
    DeviceOut,
    DeviceUpdate,
)
from magister_api.services.devices import (
    DeviceAssignmentError,
    DeviceNotFoundError,
    DevicePermissionError,
    DeviceService,
)

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", response_model=list[DeviceOut])
async def list_devices(
    user: AuthenticatedUser = Depends(require_smi),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> list[DeviceOut]:
    svc = DeviceService(session, settings, user.to_scope())
    rows = await svc.list_all()
    return [DeviceOut.model_validate(r) for r in rows]


@router.post("", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
async def create_device(
    payload: DeviceCreate,
    request: Request,
    user: AuthenticatedUser = Depends(require_smi),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> DeviceOut:
    svc = DeviceService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    row = await svc.create(
        name=payload.name,
        device_type=payload.device_type,
        serial_number=payload.serial_number,
        notes=payload.notes,
        ip=ip,
        request_id=request_id,
    )
    return DeviceOut.model_validate(row)


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(
    device_id: int,
    user: AuthenticatedUser = Depends(require_smi),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> DeviceOut:
    svc = DeviceService(session, settings, user.to_scope())
    try:
        row = await svc.get(device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="device_not_found") from exc
    return DeviceOut.model_validate(row)


@router.patch("/{device_id}", response_model=DeviceOut)
async def patch_device(
    device_id: int,
    payload: DeviceUpdate,
    request: Request,
    user: AuthenticatedUser = Depends(require_smi),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> DeviceOut:
    svc = DeviceService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        row = await svc.update(
            device_id=device_id,
            name=payload.name,
            device_type=payload.device_type,
            serial_number=payload.serial_number,
            notes=payload.notes,
            ip=ip,
            request_id=request_id,
        )
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="device_not_found") from exc
    return DeviceOut.model_validate(row)


@router.post("/{device_id}/assign", response_model=DeviceOut)
async def assign_device(
    device_id: int,
    payload: DeviceAssign,
    request: Request,
    user: AuthenticatedUser = Depends(require_smi),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> DeviceOut:
    svc = DeviceService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        row = await svc.assign(
            device_id=device_id,
            assignment_type=payload.assignment_type,
            person_guid=payload.person_guid,
            class_id=payload.class_id,
            school_id=payload.school_id,
            ip=ip,
            request_id=request_id,
        )
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="device_not_found") from exc
    except DevicePermissionError as exc:
        raise HTTPException(status_code=403, detail="school_out_of_scope") from exc
    except DeviceAssignmentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DeviceOut.model_validate(row)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_smi),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> None:
    svc = DeviceService(session, settings, user.to_scope())
    ip, request_id = _ip_request_id(request)
    try:
        await svc.delete(device_id=device_id, ip=ip, request_id=request_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="device_not_found") from exc
    return None


__all__ = ["router"]
