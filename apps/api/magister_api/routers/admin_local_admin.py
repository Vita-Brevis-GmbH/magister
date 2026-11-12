"""Admin-only lifecycle endpoints for the local break-glass account.

- ``GET    /admin/local-admin``          — status (never returns the hash)
- ``POST   /admin/local-admin/password``  — rotate the password
- ``PATCH  /admin/local-admin``           — toggle ``enabled``

The four second-factor interventions of ADR-0015 D2:

- ``GET    /admin/local-admin/mfa``               — status (no secret, no code)
- ``DELETE /admin/local-admin/mfa``               — reset: clear the factor, force re-enrolment
- ``POST   /admin/local-admin/mfa/recovery-codes`` — a fresh set of codes
- ``POST   /admin/local-admin/mfa/suspend``       — 24-hour emergency bypass

A reset never returns a secret: it only clears, and the new secret is generated
during the next enrolment by whoever logs in. Rotating the password is a
separate, separately audited action — so an operator taking over the account
leaves two entries, not one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings, get_settings
from magister_api.db import get_session
from magister_api.repositories.local_admin import LocalAdminRepository
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.local_admin import (
    LocalAdminEnabledUpdate,
    LocalAdminMfaOut,
    LocalAdminMfaSuspendRequest,
    LocalAdminOut,
    LocalAdminPasswordChangeRequest,
    LocalEnrollConfirmOut,
)
from magister_api.services.local_admin import LocalAdminService
from magister_api.services.local_admin_mfa import LocalAdminMfaService

router = APIRouter(prefix="/admin/local-admin", tags=["admin"])


@router.get("", response_model=LocalAdminOut)
async def get_local_admin(
    user: AuthenticatedUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> LocalAdminOut:
    row = await LocalAdminRepository(session).get()
    if row is None:
        raise HTTPException(status_code=404, detail="local_admin_not_configured")
    return LocalAdminOut.model_validate(row)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: Request,
    payload: LocalAdminPasswordChangeRequest,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> None:
    svc = LocalAdminService(session)
    ok = await svc.change_password(
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="invalid_current_password")
    ip, request_id = _ip_request_id(request)
    await AuditService(session, settings).emit(
        action="local_admin_password_changed",
        target_kind="local_admin",
        target_id="1",
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        school_id=None,
        ip=ip,
        request_id=request_id,
        payload={},  # deliberately empty; allowlist forbids password fields anyway
    )


@router.patch("", response_model=LocalAdminOut)
async def update_local_admin(
    request: Request,
    payload: LocalAdminEnabledUpdate,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> LocalAdminOut:
    svc = LocalAdminService(session)
    row = await svc.set_enabled(payload.enabled)
    if row is None:
        raise HTTPException(status_code=404, detail="local_admin_not_configured")
    ip, request_id = _ip_request_id(request)
    await AuditService(session, settings).emit(
        action="local_admin_enabled_changed",
        target_kind="local_admin",
        target_id="1",
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        school_id=None,
        ip=ip,
        request_id=request_id,
        payload={"enabled": payload.enabled},
    )
    return LocalAdminOut.model_validate(row)


__all__ = ["router"]


# --- Second factor: the four interventions (ADR-0015 D2) --------------------


def _mfa_out(status_obj: object) -> LocalAdminMfaOut:
    return LocalAdminMfaOut.model_validate(status_obj, from_attributes=True)


@router.get("/mfa", response_model=LocalAdminMfaOut)
async def get_local_admin_mfa(
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> LocalAdminMfaOut:
    state = await LocalAdminMfaService(session, settings).status()
    if state is None:
        raise HTTPException(status_code=404, detail="local_admin_not_configured")
    return _mfa_out(state)


@router.delete("/mfa", response_model=LocalAdminMfaOut)
async def reset_local_admin_mfa(
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> LocalAdminMfaOut:
    """Clear the second factor; the next login is forced through enrolment.

    The MFA requirement itself stays in force — this is the "lost phone" case,
    not a bypass.
    """
    ip, request_id = _ip_request_id(request)
    svc = LocalAdminMfaService(session, settings)
    if not await svc.reset(actor=user.upn):
        raise HTTPException(status_code=404, detail="local_admin_not_configured")
    await AuditService(session, settings).emit(
        action="local_totp_reset",
        target_kind="local_admin",
        target_id="1",
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        school_id=None,
        ip=ip,
        request_id=request_id,
        payload={"forces_enrollment": True},
    )
    state = await svc.status()
    if state is None:
        raise HTTPException(status_code=404, detail="local_admin_not_configured")
    return _mfa_out(state)


@router.post("/mfa/recovery-codes", response_model=LocalEnrollConfirmOut)
async def regenerate_local_admin_recovery_codes(
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> LocalEnrollConfirmOut:
    """A fresh set of recovery codes, shown once. The secret is untouched."""
    ip, request_id = _ip_request_id(request)
    codes = await LocalAdminMfaService(session, settings).regenerate_recovery_codes()
    if codes is None:
        raise HTTPException(status_code=409, detail="mfa_not_enrolled")
    await AuditService(session, settings).emit(
        action="local_recovery_codes_regenerated",
        target_kind="local_admin",
        target_id="1",
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        school_id=None,
        ip=ip,
        request_id=request_id,
        payload={"count": len(codes)},
    )
    return LocalEnrollConfirmOut(recovery_codes=codes)


@router.post("/mfa/suspend", response_model=LocalAdminMfaOut)
async def suspend_local_admin_mfa(
    request: Request,
    payload: LocalAdminMfaSuspendRequest,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> LocalAdminMfaOut:
    """Let the password alone through — for 24 hours, then never again.

    There is no duration parameter and no "off": the window always expires on
    its own. A longer bypass means granting a fresh window, which audits again.
    """
    ip, request_id = _ip_request_id(request)
    svc = LocalAdminMfaService(session, settings)
    until = await svc.suspend_requirement(actor=user.upn, reason=payload.reason)
    await AuditService(session, settings).emit(
        action="local_mfa_requirement_suspended",
        target_kind="local_admin",
        target_id="1",
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        school_id=None,
        ip=ip,
        request_id=request_id,
        payload={"until": str(until), "reason": payload.reason[:200]},
    )
    state = await svc.status()
    if state is None:
        raise HTTPException(status_code=404, detail="local_admin_not_configured")
    return _mfa_out(state)
