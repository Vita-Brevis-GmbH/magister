"""Anmeldekonten aus dem Keycloak-Realm (ADR-0025): ansehen, vorab anlegen, verwalten.

Die Benutzer selbst verwaltet Keycloak. Hier steht, was Magister über sie
weiss, und die Handgriffe, die nur Magister kann: ein Konto vorab anlegen
(damit Rollen vor der ersten Anmeldung vergeben werden können), sperren, die
Bindung an den Keycloak-Benutzer lösen und löschen. Die Rollen selbst vergibt
der Rolleneditor (``/admin/users/{guid}/roles``) mit der ``principal_guid``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from magister_api.audit.service import AuditService
from magister_api.auth.bootstrap import is_bootstrap_admin
from magister_api.auth.current_user import AuthenticatedUser
from magister_api.auth.effective_settings import get_effective_settings
from magister_api.auth.rbac import require_admin
from magister_api.config import Settings
from magister_api.db import get_session
from magister_api.models.auth import LoginAccount
from magister_api.repositories.auth import LoginAccountRepository
from magister_api.routers._helpers import _ip_request_id
from magister_api.schemas.login_accounts import (
    LoginAccountCreate,
    LoginAccountOut,
    LoginAccountUpdate,
)
from magister_api.services._user_enrich import fetch_user_labels
from magister_api.services.login_accounts import (
    LoginAccountConflictError,
    LoginAccountService,
)

router = APIRouter(prefix="/admin/login-accounts", tags=["admin"])


async def _out(
    session: AsyncSession, settings: Settings, rows: list[LoginAccount]
) -> list[LoginAccountOut]:
    ad = await fetch_user_labels(session, (r.principal_guid for r in rows))
    return [
        LoginAccountOut(
            id=r.id,
            username=r.username,
            display_name=r.display_name,
            email=r.email,
            principal_guid=r.principal_guid,
            bound=r.subject is not None,
            enabled=r.enabled,
            ad_linked=r.principal_guid in ad,
            bootstrap_admin=is_bootstrap_admin(settings, r.username),
            created_at=r.created_at,
            last_login_at=r.last_login_at,
        )
        for r in rows
    ]


async def _get(session: AsyncSession, account_id: int) -> LoginAccount:
    row = await LoginAccountRepository(session).get(account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="login_account_not_found")
    return row


async def _audit(
    request: Request,
    session: AsyncSession,
    settings: Settings,
    user: AuthenticatedUser,
    *,
    action: str,
    account: LoginAccount,
    payload: dict[str, object],
) -> None:
    ip, request_id = _ip_request_id(request)
    await AuditService(session, settings).emit(
        action=action,
        target_kind="login_account",
        target_id=str(account.id),
        actor_upn=user.upn,
        actor_object_guid=user.ad_object_guid,
        school_id=None,
        ip=ip,
        request_id=request_id,
        payload={"username": account.username, "via": "admin_ui", **payload},
    )


@router.get("", response_model=list[LoginAccountOut])
async def list_login_accounts(
    user: AuthenticatedUser = Depends(require_admin),  # noqa: ARG001
    settings: Settings = Depends(get_effective_settings),
    session: AsyncSession = Depends(get_session),
    search: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[LoginAccountOut]:
    rows = await LoginAccountRepository(session).search(search=search, limit=limit)
    return await _out(session, settings, rows)


@router.post("", response_model=LoginAccountOut, status_code=status.HTTP_201_CREATED)
async def create_login_account(
    payload: LoginAccountCreate,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_effective_settings),
    session: AsyncSession = Depends(get_session),
) -> LoginAccountOut:
    try:
        row = await LoginAccountService(session, settings).precreate(
            username=payload.username, display_name=payload.display_name
        )
    except LoginAccountConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc
    await _audit(
        request,
        session,
        settings,
        user,
        action="login_account_created",
        account=row,
        payload={"principal_guid": row.principal_guid},
    )
    return (await _out(session, settings, [row]))[0]


@router.patch("/{account_id}", response_model=LoginAccountOut)
async def update_login_account(
    account_id: int,
    payload: LoginAccountUpdate,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_effective_settings),
    session: AsyncSession = Depends(get_session),
) -> LoginAccountOut:
    row = await _get(session, account_id)
    if row.enabled != payload.enabled:
        try:
            ended = await LoginAccountService(session, settings).set_enabled(
                row, enabled=payload.enabled
            )
        except LoginAccountConflictError as exc:
            raise HTTPException(status_code=409, detail=exc.code) from exc
        await _audit(
            request,
            session,
            settings,
            user,
            action="login_account_enabled" if payload.enabled else "login_account_disabled",
            account=row,
            payload={"sessions_ended": ended},
        )
    return (await _out(session, settings, [row]))[0]


@router.post("/{account_id}/unbind", response_model=LoginAccountOut)
async def unbind_login_account(
    account_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_effective_settings),
    session: AsyncSession = Depends(get_session),
) -> LoginAccountOut:
    row = await _get(session, account_id)
    if row.subject is not None:
        ended = await LoginAccountService(session, settings).unbind(row)
        await _audit(
            request,
            session,
            settings,
            user,
            action="login_account_unbound",
            account=row,
            payload={"sessions_ended": ended},
        )
    return (await _out(session, settings, [row]))[0]


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_login_account(
    account_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_effective_settings),
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await _get(session, account_id)
    try:
        ended = await LoginAccountService(session, settings).delete(row)
    except LoginAccountConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc
    await _audit(
        request,
        session,
        settings,
        user,
        action="login_account_deleted",
        account=row,
        payload={"principal_guid": row.principal_guid, "sessions_ended": ended},
    )


__all__ = ["router"]
