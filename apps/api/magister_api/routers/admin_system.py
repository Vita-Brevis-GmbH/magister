"""Admin-only ``/admin/system`` — WebUI-triggered restart / git-update.

The API only records a request; a privileged host watcher executes it (see
:mod:`magister_api.services.system_ops`). All endpoints require admin.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.system_ops import (
    SystemCommandResponse,
    SystemCommandResult,
    SystemStatusOut,
)
from magister_api.services.system_ops import SystemOpsNotConfiguredError, SystemOpsService

router = APIRouter(prefix="/admin/system", tags=["admin"])


@router.get("/status", response_model=SystemStatusOut)
async def system_status(
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> SystemStatusOut:
    raw = SystemOpsService(session, settings).status()
    last = raw.get("last")
    return SystemStatusOut(
        configured=bool(raw["configured"]),
        pending=int(raw["pending"]),
        last=SystemCommandResult.model_validate(last) if isinstance(last, dict) else None,
    )


async def _enqueue(
    action: str,
    request: Request,
    user: AuthenticatedUser,
    settings: Settings,
    session: AsyncSession,
) -> SystemCommandResponse:
    ip, request_id = _ip_request_id(request)
    try:
        payload = await SystemOpsService(session, settings).enqueue(
            action,
            actor_upn=user.upn,
            actor_object_guid=user.ad_object_guid,
            ip=ip,
            request_id=request_id,
        )
    except SystemOpsNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ops_not_configured"
        ) from exc
    return SystemCommandResponse(
        id=payload["id"], action=payload["action"], requested_at=payload["requested_at"]
    )


@router.post("/restart", response_model=SystemCommandResponse)
async def request_restart(
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> SystemCommandResponse:
    """Queue a container restart for the host watcher to execute."""
    return await _enqueue("restart", request, user, settings, session)


@router.post("/update", response_model=SystemCommandResponse)
async def request_update(
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> SystemCommandResponse:
    """Queue a git-pull + rebuild + up for the host watcher to execute."""
    return await _enqueue("update", request, user, settings, session)


__all__ = ["router"]
